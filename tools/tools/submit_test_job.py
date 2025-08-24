from qiskit_ibm_runtime import QiskitRuntimeService, Session, Sampler
from qiskit import QuantumCircuit

def submit_bell_job(backend_name="ibm_torino"):
    service = QiskitRuntimeService()
    
    # Open a session on the chosen backend
    with Session(service=service, backend=backend_name) as session:
        # Create sampler inside session
        sampler = Sampler(session=session)
        
        # Example Bell state circuit
        qc = QuantumCircuit(2)
        qc.h(0)
        qc.cx(0, 1)
        qc.measure_all()

        # Submit the job
        job = sampler.run(qc)
        result = job.result()

    return result
