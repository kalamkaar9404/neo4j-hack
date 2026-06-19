import os
import csv
from neo4j import GraphDatabase
from dotenv import load_dotenv

# Load env variables
load_dotenv()

URI = os.getenv("NEO4J_URI")
USERNAME = os.getenv("NEO4J_USERNAME", "neo4j")
PASSWORD = os.getenv("NEO4J_PASSWORD")

# Define Category Mapping for all 41 diseases
CATEGORY_MAPPING = {
    "Fungal infection": "Dermatological",
    "Allergy": "Immune System & Allergy",
    "GERD": "Gastrointestinal",
    "Chronic cholestasis": "Gastrointestinal",
    "Drug Reaction": "Dermatological",
    "Peptic ulcer diseae": "Gastrointestinal",
    "AIDS": "Infectious Disease",
    "Diabetes": "Endocrine & Metabolic",
    "Diabetes ": "Endocrine & Metabolic",
    "Gastroenteritis": "Gastrointestinal",
    "Bronchial Asthma": "Respiratory",
    "Hypertension": "Cardiovascular",
    "Hypertension ": "Cardiovascular",
    "Migraine": "Neurological",
    "Cervical spondylosis": "Musculoskeletal",
    "Paralysis (brain hemorrhage)": "Neurological",
    "Jaundice": "Infectious Disease",
    "Malaria": "Infectious Disease",
    "Chicken pox": "Infectious Disease",
    "Dengue": "Infectious Disease",
    "Typhoid": "Infectious Disease",
    "hepatitis A": "Infectious Disease",
    "Hepatitis B": "Infectious Disease",
    "Hepatitis C": "Infectious Disease",
    "Hepatitis D": "Infectious Disease",
    "Hepatitis E": "Infectious Disease",
    "Alcoholic hepatitis": "Gastrointestinal",
    "Tuberculosis": "Infectious Disease",
    "Common Cold": "Respiratory",
    "Pneumonia": "Respiratory",
    "Dimorphic hemmorhoids(piles)": "Gastrointestinal",
    "Heart attack": "Cardiovascular",
    "Varicose veins": "Cardiovascular",
    "Hypothyroidism": "Endocrine & Metabolic",
    "Hyperthyroidism": "Endocrine & Metabolic",
    "Hypoglycemia": "Endocrine & Metabolic",
    "Osteoarthristis": "Musculoskeletal",
    "Arthritis": "Musculoskeletal",
    "(vertigo) Paroymsal  Positional Vertigo": "Neurological",
    "Acne": "Dermatological",
    "Urinary tract infection": "Urological",
    "Psoriasis": "Dermatological",
    "Impetigo": "Dermatological"
}

def setup_database():
    if not URI or not PASSWORD:
        print("Error: NEO4J_URI and NEO4J_PASSWORD must be set in your .env file.")
        return

    # 1. Parse Precautions
    precautions = {}
    precaution_file = "Disease precaution.csv"
    if os.path.exists(precaution_file):
        with open(precaution_file, mode='r', encoding='utf-8') as f:
            reader = csv.reader(f)
            next(reader) # skip header
            for row in reader:
                if not row or not row[0].strip():
                    continue
                d_name = row[0].strip()
                precs = [p.strip() for p in row[1:] if p.strip()]
                precautions[d_name] = precs
    else:
        print(f"Warning: {precaution_file} not found.")

    # 2. Parse Diseases & Symptoms
    disease_symptoms = {}
    unique_symptoms = set()
    symptom_file = "DiseaseAndSymptoms.csv"
    if os.path.exists(symptom_file):
        with open(symptom_file, mode='r', encoding='utf-8') as f:
            reader = csv.reader(f)
            next(reader) # skip header
            for row in reader:
                if not row or not row[0].strip():
                    continue
                d_name = row[0].strip()
                # Clean symptoms (remove underscores, strip whitespace, Title Case)
                syms = []
                for s in row[1:]:
                    if s.strip():
                        clean_s = s.strip().replace("_", " ").replace("  ", " ").strip().title()
                        if clean_s:
                            syms.append(clean_s)
                            unique_symptoms.add(clean_s)
                if d_name not in disease_symptoms:
                    disease_symptoms[d_name] = set()
                disease_symptoms[d_name].update(syms)
    else:
        print(f"Error: {symptom_file} not found. Ingestion aborted.")
        return

    # 3. Establish Neo4j connection and populate
    driver = GraphDatabase.driver(URI, auth=(USERNAME, PASSWORD))
    
    with driver.session() as session:
        print("Clearing Neo4j database...")
        session.run("MATCH (n) DETACH DELETE n")
        
        # Create Category nodes
        print("Creating Category nodes...")
        categories = list(set(CATEGORY_MAPPING.values()))
        for cat in categories:
            session.run("MERGE (:Category {name: $name})", name=cat)
            
        # Create Symptom nodes
        print(f"Creating {len(unique_symptoms)} Symptom nodes...")
        # Batch create symptoms
        session.run("UNWIND $symptoms AS name MERGE (:Symptom {name: name})", symptoms=list(unique_symptoms))
        
        # Create Diseases, Category relationships, and Symptom relationships
        print("Creating Disease nodes and relationships...")
        for d_name, syms in disease_symptoms.items():
            # Get category
            cat_name = CATEGORY_MAPPING.get(d_name, CATEGORY_MAPPING.get(d_name + " ", "Other"))
            
            # Create Disease & Link to Category
            session.run("""
                MERGE (d:Disease {name: $name})
                WITH d
                MATCH (c:Category {name: $cat_name})
                MERGE (d)-[:BELONGS_TO]->(c)
            """, name=d_name, cat_name=cat_name)
            
            # Create INDICATES relationships
            session.run("""
                MATCH (d:Disease {name: $d_name})
                WITH d
                UNWIND $syms AS sym_name
                MATCH (s:Symptom {name: sym_name})
                MERGE (s)-[:INDICATES]->(d)
            """, d_name=d_name, syms=list(syms))
            
            # Create Precaution nodes and link to Disease
            d_precs = precautions.get(d_name, precautions.get(d_name + " ", []))
            for prec in d_precs:
                session.run("""
                    MERGE (p:Precaution {name: $prec})
                    WITH p
                    MATCH (d:Disease {name: $d_name})
                    MERGE (d)-[:PRECAUTION_RECOMMENDED]->(p)
                """, prec=prec, d_name=d_name)

        # Let's add some mock medicines/specialists dynamically to these new diseases
        # so our graph query still returns treatments and specialists
        print("Populating Specialists and Medicines dynamically...")
        specialist_mappings = {
            "Dermatological": "Dermatologist",
            "Immune System & Allergy": "Allergist / Immunologist",
            "Gastrointestinal": "Gastroenterologist",
            "Infectious Disease": "Infectious Disease Specialist",
            "Respiratory": "Pulmonologist",
            "Cardiovascular": "Cardiologist",
            "Neurological": "Neurologist",
            "Endocrine & Metabolic": "Endocrinologist",
            "Musculoskeletal": "Rheumatologist / Orthopedist",
            "Urological": "Urologist"
        }
        
        for d_name in disease_symptoms.keys():
            cat_name = CATEGORY_MAPPING.get(d_name, CATEGORY_MAPPING.get(d_name + " ", "Other"))
            spec_name = specialist_mappings.get(cat_name, "General Physician")
            
            session.run("""
                MERGE (sp:Specialist {name: $spec_name})
                WITH sp
                MATCH (d:Disease {name: $d_name})
                MERGE (d)-[:CONSULT]->(sp)
            """, spec_name=spec_name, d_name=d_name)
            
            # Add a mock medicine/treatment based on disease name or precautions
            d_precs = precautions.get(d_name, precautions.get(d_name + " ", []))
            med_name = "Symptomatic Treatment"
            if d_precs:
                # Use the first precaution as a proxy if it looks like a medicine, or standard OTC
                med_name = d_precs[0]
            
            session.run("""
                MERGE (m:Medicine {name: $med_name})
                WITH m
                MATCH (d:Disease {name: $d_name})
                MERGE (d)-[:TREATED_BY]->(m)
            """, med_name=med_name, d_name=d_name)
            
        print("Full Knowledge Graph populated from CSVs successfully!")
        
    driver.close()

if __name__ == "__main__":
    setup_database()
