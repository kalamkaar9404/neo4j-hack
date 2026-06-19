import datetime
from neo4j import GraphDatabase

def save_consultation(driver, patient_id, symptoms, diagnosis, metadata):
    """
    Saves a consultation node with metadata and relationships to Patient, Symptom, and Disease nodes.
    
    metadata should be a dict: {
        'severity': str,
        'confidence_score': int,
        'llm_summary': str
    }
    """
    if not driver:
        print("Neo4j driver not initialized.")
        return False
        
    date_str = datetime.date.today().isoformat()
    
    query = """
    MERGE (p:Patient {id: $patient_id})
    CREATE (c:Consultation {
        date: $date,
        severity: $severity,
        confidence_score: $confidence_score,
        llm_summary: $llm_summary
    })
    CREATE (p)-[:HAD_CONSULTATION]->(c)
    
    // Connect to the resulting Disease node
    WITH p, c
    MATCH (d:Disease {name: $diagnosis})
    CREATE (c)-[:RESULTED_IN]->(d)
    
    // Connect to confirmed Symptoms
    WITH p, c
    UNWIND $symptoms AS sym_name
    MATCH (s:Symptom {name: sym_name})
    CREATE (c)-[:CONFIRMED_SYMPTOM]->(s)
    
    RETURN id(c) as consultation_id
    """
    
    try:
        with driver.session() as session:
            result = session.run(
                query,
                patient_id=patient_id,
                date=date_str,
                severity=metadata.get('severity', 'Unknown'),
                confidence_score=metadata.get('confidence_score', 0),
                llm_summary=metadata.get('llm_summary', ''),
                diagnosis=diagnosis,
                symptoms=list(symptoms)
            )
            record = result.single()
            if record:
                return record['consultation_id']
    except Exception as e:
        print(f"Error saving consultation: {e}")
        
    return False

def detect_chronic_conditions(driver, patient_id):
    """
    Checks if a patient has been diagnosed with the same disease 3 or more times.
    If so, establishes a :HAS_CHRONIC_CONDITION relationship.
    Returns a list of newly or existing identified chronic diseases.
    """
    if not driver:
        return []
        
    query = """
    MATCH (p:Patient {id: $patient_id})-[:HAD_CONSULTATION]->(c:Consultation)-[:RESULTED_IN]->(d:Disease)
    WITH p, d, count(c) as times_diagnosed
    WHERE times_diagnosed >= 3
    MERGE (p)-[:HAS_CHRONIC_CONDITION]->(d)
    RETURN d.name as chronic_disease, times_diagnosed
    """
    
    try:
        with driver.session() as session:
            result = session.run(query, patient_id=patient_id)
            return [record.data() for record in result]
    except Exception as e:
        print(f"Error detecting chronic conditions: {e}")
        
    return []

def get_patient_history(driver, patient_id):
    """
    Retrieves the clinical history of a patient, including:
    - Chronic conditions
    - Historical consultations sorted by date desc (with symptoms, diagnosis, and metadata)
    """
    if not driver:
        return {"chronic_conditions": [], "consultations": []}
        
    # Get chronic conditions
    chronic_query = """
    MATCH (p:Patient {id: $patient_id})-[:HAS_CHRONIC_CONDITION]->(d:Disease)
    RETURN d.name as name
    """
    
    # Get last 5 consultations
    consultations_query = """
    MATCH (p:Patient {id: $patient_id})-[:HAD_CONSULTATION]->(c:Consultation)-[:RESULTED_IN]->(d:Disease)
    OPTIONAL MATCH (c)-[:CONFIRMED_SYMPTOM]->(s:Symptom)
    RETURN c.date as date,
           c.severity as severity,
           c.confidence_score as confidence_score,
           c.llm_summary as llm_summary,
           d.name as diagnosis,
           collect(s.name) as symptoms
    ORDER BY c.date DESC
    LIMIT 5
    """
    
    history = {
        "chronic_conditions": [],
        "consultations": []
    }
    
    try:
        with driver.session() as session:
            # Fetch chronic conditions
            chronic_res = session.run(chronic_query, patient_id=patient_id)
            history["chronic_conditions"] = [r["name"] for r in chronic_res]
            
            # Fetch consultations
            consultation_res = session.run(consultations_query, patient_id=patient_id)
            history["consultations"] = [r.data() for r in consultation_res]
    except Exception as e:
        print(f"Error fetching patient history: {e}")
        
    return history
