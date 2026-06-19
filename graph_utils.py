import os
from neo4j import GraphDatabase
from pyvis.network import Network
from dotenv import load_dotenv

# Load env variables
load_dotenv()

URI = os.getenv("NEO4J_URI")
USERNAME = os.getenv("NEO4J_USERNAME", "neo4j")
PASSWORD = os.getenv("NEO4J_PASSWORD")

def get_driver():
    if not URI or not PASSWORD:
        return None
    try:
        return GraphDatabase.driver(URI, auth=(USERNAME, PASSWORD))
    except Exception as e:
        print(f"Error creating Neo4j driver: {e}")
        return None

def query_graphrag_context(driver, symptoms):
    if not driver:
        print("Neo4j driver not initialized.")
        return []
    if not symptoms:
        return []
        
    query = """
    MATCH (s:Symptom)-[:INDICATES]->(d:Disease)
    WHERE s.name IN $symptoms
    WITH d, count(s) as match_score, collect(s.name) as matched_symptoms
    ORDER BY match_score DESC LIMIT 2
    
    OPTIONAL MATCH (d)-[:BELONGS_TO]->(c:Category)
    OPTIONAL MATCH (d)-[:TREATED_BY]->(m:Medicine)
    OPTIONAL MATCH (d)-[:CONSULT]->(sp:Specialist)
    OPTIONAL MATCH (d)-[:PRECAUTION_RECOMMENDED]->(p:Precaution)
    
    RETURN d.name as disease, 
           match_score, 
           matched_symptoms, 
           c.name as category,
           collect(DISTINCT m.name) as medicines, 
           collect(DISTINCT sp.name) as specialists,
           collect(DISTINCT p.name) as precautions
    """
    
    try:
        with driver.session() as session:
            result = session.run(query, symptoms=symptoms)
            return [record.data() for record in result]
    except Exception as e:
        print(f"Error querying Neo4j: {e}")
        return []

def find_candidate_diseases(driver, confirmed_symptoms):
    if not driver or not confirmed_symptoms:
        return []
    query = """
    MATCH (s:Symptom)-[:INDICATES]->(d:Disease)
    WHERE s.name IN $confirmed
    WITH d, count(s) as match_score, collect(s.name) as matched
    ORDER BY match_score DESC
    RETURN d.name as disease, match_score, matched
    LIMIT 5
    """
    try:
        with driver.session() as session:
            res = session.run(query, confirmed=list(confirmed_symptoms))
            return [r.data() for r in res]
    except Exception as e:
        print(f"Error finding candidate diseases: {e}")
        return []

def get_next_clarifying_symptom(driver, confirmed_symptoms, ruled_out_symptoms, candidate_diseases):
    if not driver or not candidate_diseases:
        return None
        
    disease_names = [d['disease'] for d in candidate_diseases]
    exclude = list(confirmed_symptoms) + list(ruled_out_symptoms)
    
    query = """
    MATCH (s:Symptom)-[:INDICATES]->(d:Disease)
    WHERE d.name IN $diseases AND NOT s.name IN $exclude
    RETURN s.name as symptom, count(d) as freq
    ORDER BY freq DESC, symptom ASC
    LIMIT 3
    """
    try:
        with driver.session() as session:
            res = session.run(query, diseases=disease_names, exclude=exclude)
            records = [r.data() for r in res]
            if records:
                # Return the symptom that matches the most candidates to narrow down
                return records[0]['symptom']
    except Exception as e:
        print(f"Error getting next clarifying symptom: {e}")
    return None

def render_graph_visual(context_data):
    # Setup PyVis Network (dark theme ready)
    net = Network(height='450px', width='100%', bgcolor='#0E1117', font_color='white')
    net.barnes_hut()
    
    added_nodes = set()
    
    for record in context_data:
        disease = record['disease']
        
        # Add Disease node
        if disease not in added_nodes:
            net.add_node(disease, label=disease, color='#FF4B4B', size=25, shape='ellipse', title=f"Disease: {disease}")
            added_nodes.add(disease)
            
        # Add Category node
        if record.get('category'):
            cat = record['category']
            if cat not in added_nodes:
                net.add_node(cat, label=cat, color='#9B5DE5', size=20, shape='hexagon', title=f"Category: {cat}")
                added_nodes.add(cat)
            net.add_edge(disease, cat, label="BELONGS_TO", color='#9B5DE5', arrows='to')
            
        # Add Symptom nodes
        for sym in record['matched_symptoms']:
            if sym not in added_nodes:
                net.add_node(sym, label=sym, color='#F1A70A', size=15, shape='dot', title=f"Symptom: {sym}")
                added_nodes.add(sym)
            net.add_edge(sym, disease, label="INDICATES", color='#F1A70A', arrows='to')
            
        # Add Medicine nodes
        for med in record['medicines']:
            if med:
                if med not in added_nodes:
                    net.add_node(med, label=med, color='#00C49F', size=18, shape='box', title=f"Medicine: {med}")
                    added_nodes.add(med)
                net.add_edge(disease, med, label="TREATED_BY", color='#00C49F', arrows='to')
                
        # Add Specialist nodes
        for sp in record['specialists']:
            if sp:
                if sp not in added_nodes:
                    net.add_node(sp, label=sp, color='#0088FE', size=18, shape='star', title=f"Specialist: {sp}")
                    added_nodes.add(sp)
                net.add_edge(disease, sp, label="CONSULT", color='#0088FE', arrows='to')
                
        # Add Precaution nodes
        for prec in record.get('precautions', []):
            if prec:
                if prec not in added_nodes:
                    net.add_node(prec, label=prec, color='#FF85A2', size=16, shape='triangle', title=f"Precaution: {prec}")
                    added_nodes.add(prec)
                net.add_edge(disease, prec, label="PRECAUTION_RECOMMENDED", color='#FF85A2', arrows='to')
                
    try:
        net.save_graph("temp_graph.html")
        with open("temp_graph.html", 'r', encoding='utf-8') as f:
            html_data = f.read()
        if os.path.exists("temp_graph.html"):
            os.remove("temp_graph.html")
        return html_data
    except Exception as e:
        print(f"Error rendering network visualization: {e}")
        return ""

def render_patient_history_visual(history, patient_id):
    # Setup PyVis Network (dark theme ready)
    net = Network(height='350px', width='100%', bgcolor='#0E1117', font_color='white')
    net.barnes_hut()
    
    added_nodes = set()
    
    # Add Patient root node
    patient_label = f"Patient:\n{patient_id}"
    net.add_node(patient_id, label=patient_label, color='#00D4FF', size=28, shape='dot', title=f"Patient: {patient_id}")
    added_nodes.add(patient_id)
    
    # Add Chronic Condition nodes and direct links
    for disease in history.get("chronic_conditions", []):
        if disease not in added_nodes:
            net.add_node(disease, label=disease, color='#FF4B4B', size=22, shape='ellipse', title=f"Chronic Condition: {disease}")
            added_nodes.add(disease)
        net.add_edge(patient_id, disease, label="HAS_CHRONIC_CONDITION", color='#FFD700', width=3, arrows='to')
        
    # Add Consultations
    for idx, consult in enumerate(history.get("consultations", [])):
        date_str = consult.get("date", "Unknown Date")
        diag = consult.get("diagnosis", "Unknown Diagnosis")
        c_id = f"consult_{idx}_{date_str}"
        
        # Add Consultation node
        c_label = f"Consultation\n({date_str})"
        c_title = f"Date: {date_str}\nSeverity: {consult.get('severity')}\nConfidence: {consult.get('confidence_score')}%"
        net.add_node(c_id, label=c_label, color='#9B5DE5', size=18, shape='hexagon', title=c_title)
        net.add_edge(patient_id, c_id, label="HAD_CONSULTATION", color='#9B5DE5', arrows='to')
        
        # Add and connect Disease node
        if diag not in added_nodes:
            net.add_node(diag, label=diag, color='#FF4B4B', size=22, shape='ellipse', title=f"Disease: {diag}")
            added_nodes.add(diag)
        net.add_edge(c_id, diag, label="RESULTED_IN", color='#FF4B4B', arrows='to')
        
        # Add and connect confirmed Symptoms
        for sym in consult.get("symptoms", []):
            if sym not in added_nodes:
                net.add_node(sym, label=sym, color='#F1A70A', size=14, shape='dot', title=f"Symptom: {sym}")
                added_nodes.add(sym)
            net.add_edge(c_id, sym, label="CONFIRMED_SYMPTOM", color='#F1A70A', arrows='to')
            
    try:
        net.save_graph("temp_history_graph.html")
        with open("temp_history_graph.html", 'r', encoding='utf-8') as f:
            html_data = f.read()
        if os.path.exists("temp_history_graph.html"):
            os.remove("temp_history_graph.html")
        return html_data
    except Exception as e:
        print(f"Error rendering history network visualization: {e}")
        return ""

