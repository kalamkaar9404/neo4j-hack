import os
import json
from groq import Groq
from dotenv import load_dotenv

# Load env variables
load_dotenv()

# Initialize Groq Client
api_key = os.getenv("GROQ_API_KEY")
client = Groq(api_key=api_key) if api_key else None

# Best available free models
MODEL = "llama-3.3-70b-versatile"

def extract_symptoms(user_text, all_symptoms):
    if not all_symptoms:
        all_symptoms = ["Fever", "Cough", "Fatigue", "Vomiting", "Nausea", "Dizziness", "Chest Pain", "Shortness of Breath", "Headache", "Runny Nose"]
        
    if not client:
        # Simple string matching fallback
        found = [s for s in all_symptoms if s.lower() in user_text.lower()]
        return found
        
    prompt = f"""
    You are a clinical assistant. Extract a list of symptoms from the following user query:
    "{user_text}"
    
    You must ONLY extract symptoms that match or are highly synonymous with this list of allowed symptoms: 
    {json.dumps(all_symptoms)}
    
    Map any matched symptoms to their exact spelling in the allowed list above.
    Return ONLY a raw JSON array of strings containing the matched symptoms. Do not include any markdown format (like ```json), conversation, or extra text.
    Example output: ["Fever", "Cough"]
    """
    
    try:
        response = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=MODEL,
            temperature=0.0
        )
        content = response.choices[0].message.content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1]
        if content.endswith("```"):
            content = content.rsplit("\n", 1)[0]
        content = content.strip().strip("`").strip()
        
        return json.loads(content)
    except Exception as e:
        print(f"Error during symptom extraction: {e}")
        # Substring matching fallback
        return [s for s in all_symptoms if s.lower() in user_text.lower()]

def analyze_response(user_text, current_symptom, all_symptoms):
    if not client:
        text_lower = user_text.lower()
        confirmed = None
        if any(w in text_lower for w in ["yes", "yeah", "yep", "i have", "correct", "true", "indeed", "sore"]):
            confirmed = True
        elif any(w in text_lower for w in ["no", "nah", "nope", "i dont", "false", "neither", "don't"]):
            confirmed = False
        additional = [s for s in all_symptoms if s.lower() in text_lower and s.lower() != current_symptom.lower()]
        return {"confirmed": confirmed, "additional_symptoms": additional}

    prompt = f"""
    The doctor asked the patient if they have the symptom: "{current_symptom}".
    The patient responded: "{user_text}".
    
    Analyze the patient's response and extract:
    1. Did they confirm having "{current_symptom}"? (Respond with true, false, or null if they avoided/didn't answer).
    2. Did they mention any other symptoms they have? Choose only from this allowed list of symptoms:
    {json.dumps(all_symptoms)}
    
    Return ONLY a raw JSON object with keys:
    "confirmed": boolean or null,
    "additional_symptoms": list of strings (symptoms from the allowed list).
    
    Do not include any explanation or markdown formatting.
    """
    try:
        response = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=MODEL,
            temperature=0.0
        )
        content = response.choices[0].message.content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1]
        if content.endswith("```"):
            content = content.rsplit("\n", 1)[0]
        content = content.strip().strip("`").strip()
        return json.loads(content)
    except Exception as e:
        print(f"Error analyzing patient response: {e}")
        return {"confirmed": None, "additional_symptoms": []}

def generate_explanation(confirmed_symptoms, graph_context, patient_history=None):
    if not client:
        return "Warning: GROQ_API_KEY not configured. Please add it to your .env file to generate LLM explanations."
        
    history_str = ""
    if patient_history:
        history_str = f"\nPatient Medical History Context:\n{json.dumps(patient_history, indent=2)}\n"
        
    prompt = f"""
    You are a caring medical doctor explaining potential health conditions to a patient. 
    Explain the findings clearly based ONLY on the retrieved graph database context.
    {history_str}
    Confirmed Symptoms: {json.dumps(list(confirmed_symptoms))}
    
    Graph Database (Neo4j) Context:
    {json.dumps(graph_context, indent=2)}
    
    Based ONLY on the retrieved graph database context and patient history (if relevant/chronic):
    1. Explain which diseases are most likely (based on matching symptoms in the graph).
    2. Explain the category of the diseases found (e.g. Respiratory, Gastrointestinal).
    3. State recommended precautions/actions to take based on precautions linked in the graph.
    4. State recommended medicines and specialists to consult as linked in the graph.
    5. If patient history indicates chronic conditions or previous occurrences of the same disease, mention this or note any longitudinal patterns (e.g. 'Since you have a history of asthma...').
    
    CRITICAL INSTRUCTIONS:
    - Write in a professional, empathetic, doctor-like tone.
    - Restrict your explanation strictly to the facts retrieved from the graph database context and provided history. Do not invent details.
    - End with a clear disclaimer: "DISCLAIMER: This is for educational and demo purposes only. This tool is not a substitute for professional medical advice, diagnosis, or treatment."
    """
    
    try:
        response = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=MODEL,
            temperature=0.2
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"Error generating explanation: {e}"

def generate_consultation_summary(confirmed_symptoms, diagnosis):
    if not client:
        return f"Patient presented with {', '.join(confirmed_symptoms)} and was diagnosed with {diagnosis}."
        
    prompt = f"""
    Create a brief, 1-sentence clinical summary of a patient's consultation.
    Confirmed Symptoms: {json.dumps(list(confirmed_symptoms))}
    Resulting Diagnosis: {diagnosis}
    
    Example Output: "Patient presented with fever and cough, resulting in a diagnosis of Common Cold."
    Return ONLY the 1-sentence summary, no other text or explanation.
    """
    try:
        response = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=MODEL,
            temperature=0.0
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Error generating summary: {e}")
        return f"Patient presented with {', '.join(confirmed_symptoms)} and was diagnosed with {diagnosis}."

def generate_patient_greeting(patient_id, history):
    if not client or not history.get("consultations"):
        return f"Hello! I am your MedGraph AI clinical assistant. Please describe the symptoms you are experiencing today."
        
    prompt = f"""
    You are a caring clinical assistant greeting a returning patient: "{patient_id}".
    Here is their medical history:
    {json.dumps(history, indent=2)}
    
    Write a brief, warm, empathetic welcome-back greeting. Mention that you have reviewed their history (briefly citing a past diagnosis or chronic condition if relevant) and ask how they are feeling today or if they have any new symptoms.
    Keep it to 2-3 sentences.
    """
    try:
        response = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=MODEL,
            temperature=0.3
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Error generating patient greeting: {e}")
        return f"Welcome back, {patient_id}! I've loaded your history. How can I help you today?"

