# jobs-tracker/app.py
import os
import math
import streamlit as st
import matplotlib.pyplot as plt
import pandas as pd
from qiskit import QuantumCircuit, transpile
from qiskit.circuit.random import random_circuit
from qiskit_ibm_runtime import QiskitRuntimeService, SamplerV2
import streamlit as st

api_token = st.secrets["IQP_API_TOKEN"]
instance = st.secrets["IQP_INSTANCE"]


# ----------------- CONFIG -----------------
st.set_page_config(page_title="Quantum Job Tracker", page_icon="🧪", layout="wide")

# small UI polish
st.markdown("""
    <style>
        .title { font-size: 36px; font-weight:700;
                 background: -webkit-linear-gradient(90deg,#7928CA,#FF0080);
                 -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .stat-card { padding:12px; border-radius:10px; background: rgba(255,255,255,0.02); }
    </style>
""", unsafe_allow_html=True)

# ----------------- HELPERS -----------------
@st.cache_resource(show_spinner=False)
def get_service_cached():
    token = None
    try:
        token = st.secrets.get("IQP_API_TOKEN")
    except Exception:
        token = None
    if not token:
        token = os.getenv("IQP_API_TOKEN") or os.getenv("IQP_API_KEY")

    instance = None
    try:
        instance = st.secrets.get("IQP_INSTANCE")
    except Exception:
        instance = None
    if not instance:
        instance = os.getenv("IQP_INSTANCE")

    try:
        if token:
            svc = QiskitRuntimeService(channel="ibm_cloud", token=token, instance=instance)
        else:
            svc = QiskitRuntimeService(channel="ibm_cloud")
        _ = svc.backends(limit=1)
        return svc
    except Exception as e:
        st.error("❌ Could not connect to IBM Quantum service. Put your API token in Streamlit secrets or IQP_API_TOKEN env.")
        st.exception(e)
        return None


def safe_counts_from_result(result):
    try:
        c = result[0].data.meas.get_counts()
        if c:
            return dict(c)
    except Exception:
        pass
    try:
        d = getattr(result, "data", None)
        if d and hasattr(d, "meas") and hasattr(d.meas, "get_counts"):
            return dict(d.meas.get_counts())
    except Exception:
        pass
    try:
        if isinstance(result, dict):
            for k in ("counts", "measurement_counts", "meas_counts"):
                if k in result:
                    return dict(result[k])
    except Exception:
        pass
    try:
        if isinstance(result, (list, tuple)) and len(result) > 0:
            for entry in result:
                try:
                    if hasattr(entry, "data") and hasattr(entry.data, "meas") and hasattr(entry.data.meas, "get_counts"):
                        return dict(entry.data.meas.get_counts())
                except Exception:
                    continue
    except Exception:
        pass
    return None


def fetch_jobs_for_backend(backend_name: str, limit: int = 10, fetch_multiplier: int = 4):
    svc = get_service_cached()
    if not svc or not backend_name:
        return []
    to_request = max(limit * fetch_multiplier, limit + 5)
    try:
        raw_jobs = list(svc.jobs(limit=to_request, descending=True))
    except Exception as e:
        st.warning("Could not fetch jobs from IBM API.")
        raw_jobs = []

    job_objs = st.session_state.get("job_objs", {})
    result_meta = []
    for j in raw_jobs:
        try:
            bname = j.backend().name if j.backend() else None
        except Exception:
            bname = None
        if bname != backend_name:
            continue

        meta = {
            "job_id": j.job_id(),
            "backend": bname or "n/a",
            "status": j.status().name if hasattr(j.status(), "name") else str(j.status()),
            "created": str(getattr(j, "creation_date", "")),
            "tags": None
        }
        try:
            if hasattr(j, "tags") and callable(getattr(j, "tags")):
                t = j.tags()
                meta["tags"] = list(t) if t else None
            elif hasattr(j, "tags"):
                meta["tags"] = list(j.tags) if j.tags else None
        except Exception:
            meta["tags"] = None

        result_meta.append(meta)
        job_objs[j.job_id()] = j
        if len(result_meta) >= limit:
            break

    st.session_state["job_objs"] = job_objs
    return result_meta


def display_job_results(job_id: str):
    svc = get_service_cached()
    if not svc:
        st.error("No IBM service connection.")
        return
    job_obj = st.session_state.get("job_objs", {}).get(job_id)
    if not job_obj:
        try:
            job_obj = svc.job(job_id)
            st.session_state.setdefault("job_objs", {})[job_id] = job_obj
        except Exception as e:
            st.error("Could not fetch job object from IBM service.")
            st.exception(e)
            return
    try:
        result = job_obj.result()
    except Exception as e:
        st.error("Could not fetch job result (maybe job not finished or permission issue).")
        st.exception(e)
        return

    st.write("**Backend:**", job_obj.backend().name if job_obj.backend() else "n/a")
    st.write("**Status:**", job_obj.status())
    st.write("**Created:**", getattr(job_obj, "creation_date", "n/a"))

    counts = safe_counts_from_result(result)
    if counts:
        df = pd.DataFrame(list(counts.items()), columns=["State", "Count"])
        df["Probability"] = df["Count"] / df["Count"].sum()
        df["Percent"] = (df["Probability"] * 100).round(2)

        st.write("### Measurement Counts")
        st.dataframe(df.sort_values("Count", ascending=False), use_container_width=True)

        col1, col2 = st.columns([1, 1])
        with col1:
            fig, ax = plt.subplots(figsize=(6, 4))
            ax.bar(df["State"], df["Count"])
            ax.set_xlabel("State"); ax.set_ylabel("Counts"); ax.set_title("Counts")
            plt.xticks(rotation=45)
            st.pyplot(fig)
        with col2:
            fig2, ax2 = plt.subplots(figsize=(6, 4))
            ax2.pie(df["Count"], labels=df["State"], autopct="%1.1f%%")
            ax2.axis("equal")
            st.pyplot(fig2)
    else:
        st.info("No classical counts were found for this job (it may be an estimator or non-measurement job).")
        try:
            st.subheader("Raw result (debug)")
            if isinstance(result, (list, tuple)) and len(result) > 0:
                st.write(result[0].data if hasattr(result[0], "data") else str(result[0]))
            else:
                st.write(str(result))
        except Exception as e:
            st.write("Unable to show raw result.")
            st.exception(e)


# ----------------- UI -----------------
st.sidebar.title("⚙️ Controls")
nav = st.sidebar.radio("Navigation", ["🏠 Dashboard", "⚗️ Submit Experiment", "📂 Jobs", "📊 Results"])

svc = get_service_cached()
st.markdown("<h1 class='title'>🔬 Quantum Job Tracker</h1>", unsafe_allow_html=True)
if not svc:
    st.stop()

try:
    backend_objs = svc.backends()
    backend_names = [b.name for b in backend_objs]
except Exception:
    backend_names = []

if not backend_names:
    st.error("No backends available (or failed to fetch backends).")
    st.stop()

default_name = "ibm_torino" if "ibm_torino" in backend_names else backend_names[0]
backend_name = st.sidebar.selectbox("🎛️ Choose backend", backend_names, index=backend_names.index(default_name))

# ------------ Dashboard ------------
if nav == "🏠 Dashboard":
    st.markdown("""
    ## 📌 What is this?

    This is a **Quantum Jobs Dashboard** built on top of IBM Quantum.  
    It helps you run, track, and analyze your **quantum experiments** (called *jobs*) directly in the cloud.

    ### 🔍 Why is this useful?
    - ✅ Beginner-friendly interface instead of IBM’s raw API  
    - 🎓 Great for teaching and learning quantum basics  
    - 🧑‍🔬 Track experiments over time in one clean place   

    ### 🧭 How to use?
    - Go to **Submit Experiment** → run circuits like Bell or GHZ  
    - Open **Jobs** → see a list of all submitted jobs  
    - Check **Results** → view probabilities & charts for measurements  
    """)

# ------------ Submit Experiment ------------
elif nav == "⚗️ Submit Experiment":
    st.info("🧪 **Submit Experiment** → Run pre-built quantum circuits (Bell, GHZ, Grover, Random) on IBM Quantum backends. Adjust shots to control how many times the circuit is executed.")

    st.subheader("⚗️ Submit a quantum experiment")
    exp_choice = st.selectbox("Choose", ["Bell State", "GHZ State", "Grover Search", "Random Circuit"])
    width = depth = None
    if exp_choice == "Random Circuit":
        width = st.slider("Width (qubits)", 2, 6, 3)
        depth = st.slider("Depth (layers)", 1, 20, 5)
    shots = st.slider("Shots", 100, 2048, 1024, step=100)

    if st.button("🚀 Submit", type="primary"):
        try:
            backend_obj = svc.backend(backend_name)
            if exp_choice == "Bell State":
                qc = QuantumCircuit(2); qc.h(0); qc.cx(0, 1); qc.measure_all()
            elif exp_choice == "GHZ State":
                qc = QuantumCircuit(3); qc.h(0); qc.cx(0,1); qc.cx(0,2); qc.measure_all()
            elif exp_choice == "Grover Search":
                qc = QuantumCircuit(2); qc.h([0,1]); qc.cz(0,1); qc.h([0,1]); qc.measure_all()
            else:
                qc = random_circuit(width, depth, measure=True)

            qc_t = transpile(qc, backend=backend_obj)
            sampler = SamplerV2(backend_obj)
            try:
                job = sampler.run([qc_t], shots=shots)
            except TypeError:
                job = sampler.run([qc_t])

            st.session_state["last_job_id"] = job.job_id()
            st.session_state.setdefault("job_objs", {})[job.job_id()] = job
            st.success(f"✅ Job submitted successfully! (ID: {job.job_id()})")
        except Exception as e:
            st.error("Failed to submit job.")
            st.exception(e)

# ------------ Jobs ------------
elif nav == "📂 Jobs":
    st.info("📂 **Jobs** → Shows a history of experiments you submitted. Each job corresponds to a real quantum circuit run on IBM Quantum. Click **View Results** to inspect outcomes.")

    st.subheader("📂 Recent jobs")
    colA, colB = st.columns([1, 1])
    with colA:
        refresh = st.button("🔄 Refresh job list")
    with colB:
        limit = st.slider("How many recent jobs to show", 3, 30, 12)

    prev_limit = st.session_state.get("jobs_limit", None)
    if refresh or prev_limit != limit or "jobs_loaded_once" not in st.session_state:
        jobs_meta = fetch_jobs_for_backend(backend_name, limit=limit, fetch_multiplier=4)
        st.session_state["jobs_meta"] = jobs_meta
        st.session_state["jobs_limit"] = limit
        st.session_state["jobs_loaded_once"] = True
    else:
        jobs_meta = st.session_state.get("jobs_meta", [])

    if not jobs_meta:
        st.info("No jobs found for this backend (try refreshing or submit one).")
    else:
        for meta in jobs_meta:
            job_id = meta["job_id"]
            with st.expander(f"📌 Job {job_id[:8]}... — {meta['status']}", expanded=False):
                st.write("**Backend:**", meta["backend"])
                st.write("**Status:**", meta["status"])
                st.write("**Created:**", meta["created"])
                st.write("**Tags:**", meta["tags"] or "None")
                if st.button("📊 View Results", key=f"view_{job_id}"):
                    display_job_results(job_id)
                    st.session_state["last_job_id"] = job_id

# ------------ Results ------------
elif nav == "📊 Results":
    st.info("📊 **Results** → Displays detailed measurement outcomes from your latest experiment. Includes probabilities, counts, and visualizations for easy understanding.")

    st.subheader("📊 Results")
    job_id = st.session_state.get("last_job_id", None)
    if not job_id:
        st.info("No job selected. Open **Jobs → View Results** or submit a new experiment first.")
    else:
        display_job_results(job_id)

# ------------- Footer -------------
if "last_job_id" in st.session_state:
    st.sidebar.caption(f"🆔 Last submitted job: {st.session_state['last_job_id'][:10]}...")
