from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any

from owlready2 import get_ontology, sync_reasoner

# ----------------------------
# Configuration
# ----------------------------
ONTO_PATH = "geometry-its.owl"
FRONTEND_ORIGIN = "http://localhost:3000"

ALLOW_ALL_ORIGINS = True  # dev / prototype

# ----------------------------
# FastAPI app + CORS
# ----------------------------
app = FastAPI(title="Geometry ITS Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if ALLOW_ALL_ORIGINS else [FRONTEND_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------------
# Load ontology at startup
# ----------------------------
print(f"Loading ontology: {ONTO_PATH}")
onto = get_ontology(ONTO_PATH).load()
print("Ontology loaded.")

# Resolve core classes (must exist in ontology)
try:
    GeometricConcept = onto.GeometricConcept
    Problem = onto.Problem
    StudentModel = onto.StudentModel
except Exception as e:
    raise RuntimeError(
        "Ontology is missing required classes (GeometricConcept, Problem, StudentModel). "
        "Check ontology schema."
    ) from e

# Teacher individual
VirtualTeacher = onto.search_one(iri="*#VirtualTeacher1")

# In-memory cache for student known concepts (prototype storage)
student_cache: Dict[str, List[str]] = {}

# ----------------------------
# Utilities
# ----------------------------
def first_literal(ind, prop: str):
    vals = getattr(ind, prop, [])
    return vals[0] if vals else None

def run_reasoner():
    """Run OWL+SWRL reasoning."""
    sync_reasoner(onto, infer_property_values=True)

def build_concept_index() -> Dict[str, Any]:
    """Build concept_code -> OWL individual index."""
    idx = {}
    for c in GeometricConcept.instances():
        code = first_literal(c, "hasConceptCode")
        if code:
            idx[str(code)] = c
    return idx

concept_index = build_concept_index()

def concept_to_dict(c) -> dict:
    code = first_literal(c, "hasConceptCode")
    label = first_literal(c, "label") or c.name
    desc = first_literal(c, "hasDescription")
    diff = first_literal(c, "hasDifficultyLevel")
    ks = first_literal(c, "hasKSLevel")

    prereq_codes: List[str] = []
    for p in getattr(c, "hasPrerequisite", []):
        pc = first_literal(p, "hasConceptCode")
        if pc:
            prereq_codes.append(str(pc))

    return {
        "iri": c.iri,
        "code": str(code) if code else "",
        "label": str(label),
        "description": str(desc) if desc is not None else None,
        "difficulty": int(diff) if diff is not None else None,
        "ks_level": int(ks) if ks is not None else None,
        "prerequisites": prereq_codes,
        # auto-mapping: /public/shapes/{image_key}.png in Next.js
        "image_key": str(code) if code else None,
    }

def problem_to_dict(p) -> dict:
    label = first_literal(p, "label") or p.name
    text = first_literal(p, "hasProblemText") or ""
    ans = first_literal(p, "hasCorrectAnswer") or ""

    concept_code = None
    teaches = getattr(p, "teachesConcept", [])
    if teaches:
        c = teaches[0]
        cc = first_literal(c, "hasConceptCode")
        if cc:
            concept_code = str(cc)

    return {
        "iri": p.iri,
        "label": str(label),
        "text": str(text),
        "correct_answer": str(ans),
        "concept_code": concept_code,
    }

def get_or_create_student(student_id: str):
    """Get or create OWL individual Student_{id}."""
    s = onto.search_one(iri=f"*#Student_{student_id}")
    if s:
        return s
    with onto:
        return StudentModel(f"Student_{student_id}")

def update_student_in_ontology(student_id: str, known_codes: List[str]):
    """
    Update StudentModel individual with knowsConcept assertions
    and run reasoner to infer needsToLearn etc.
    """
    # cache (prevents accidental overwrites across requests)
    student_cache[student_id] = list(dict.fromkeys(known_codes))

    s = get_or_create_student(student_id)

    # Clear + repopulate knowsConcept
    s.knowsConcept = []
    for code in student_cache[student_id]:
        c_ind = concept_index.get(code)
        if c_ind:
            s.knowsConcept.append(c_ind)

    run_reasoner()
    return s

def student_recommendations(s_ind) -> List[dict]:
    """Read inferred needsToLearn(Student, Concept)."""
    recs = []
    for c in getattr(s_ind, "needsToLearn", []):
        recs.append(concept_to_dict(c))
    return recs

def teacher_recommendations() -> List[dict]:
    """Read recommendsConcept(VirtualTeacher1, Concept)."""
    if not VirtualTeacher:
        return []
    return [concept_to_dict(c) for c in getattr(VirtualTeacher, "recommendsConcept", [])]

def teacher_misconceptions() -> List[dict]:
    """Read detectsMisconception(VirtualTeacher1, MisconceptionPattern)."""
    if not VirtualTeacher:
        return []
    out = []
    for m in getattr(VirtualTeacher, "detectsMisconception", []):
        code = first_literal(m, "addressesConceptCode")
        if code:
            out.append({
                "concept_code": str(code),
                "message": f"The system detected a possible misconception related to concept: {code}"
            })
    return out

# ----------------------------
# Request models
# ----------------------------
class StudentUpdateRequest(BaseModel):
    student_id: str
    known_concepts: List[str]

# ----------------------------
# API Endpoints
# ----------------------------
@app.get("/concepts")
def list_concepts():
    return [concept_to_dict(c) for c in GeometricConcept.instances()]

@app.get("/concept/{code}")
def get_concept(code: str):
    c = concept_index.get(code)
    if not c:
        raise HTTPException(status_code=404, detail="Concept not found")
    return concept_to_dict(c)

@app.get("/problems")
def list_problems(concept_code: Optional[str] = None):
    results = []
    for p in Problem.instances():
        d = problem_to_dict(p)
        if concept_code is None or d["concept_code"] == concept_code:
            results.append(d)
    return results

@app.post("/student/update")
def student_update(req: StudentUpdateRequest):
    s_ind = update_student_in_ontology(req.student_id, req.known_concepts)
    recs = student_recommendations(s_ind)
    miscon = teacher_misconceptions()

    return {
        "student": {
            "student_id": req.student_id,
            "known_concepts": student_cache.get(req.student_id, []),
        },
        "recommended_concepts": recs,
        "misconceptions": miscon,
    }

@app.get("/recommend/{student_id}")
def recommend(student_id: str):
    s_ind = get_or_create_student(student_id)
    run_reasoner()
    return {"concepts": student_recommendations(s_ind)}

@app.get("/teacher/recommend/{student_id}")
def teacher_recommend(student_id: str):
    # ensure student exists (ties teacher outputs to current ontology state)
    get_or_create_student(student_id)
    run_reasoner()
    return {
        "recommended_concepts": teacher_recommendations(),
        "misconceptions": teacher_misconceptions(),
    }