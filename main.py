from typing import List, Optional
import logging
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from owlready2 import get_ontology, default_world


app = FastAPI(title="Geometry ITS Backend")


# origins = [
#     "http://localhost:3000",
#     "http://127.0.0.1:3000",
# ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ONTOLOGY_PATH = "geometry-its.owl"

print("Loading ontology...")
onto = get_ontology(ONTOLOGY_PATH).load()
print("Ontology loaded.")


# =========================
# Pydantic Models
# =========================

class Concept(BaseModel):
    iri: str
    code: Optional[str]
    label: str
    description: Optional[str] = None
    difficulty: Optional[int] = None
    prerequisites: List[str]
    image_key: Optional[str] = None  # used by frontend to map to PNG


class Problem(BaseModel):
    iri: str
    label: str
    text: str
    teaches_concepts: List[str]
    has_hint_concepts: List[str]


class AnswerRequest(BaseModel):
    problem_iri: str
    answer: str


class AnswerResult(BaseModel):
    correct: bool
    correct_answer: Optional[str]
    feedback: str


class NextConceptsRequest(BaseModel):
    mastered_concepts: List[str]


# =========================
# Helper functions
# =========================

def get_label(entity) -> str:
    if hasattr(entity, "label") and entity.label:
        return entity.label[0]
    return entity.name  # fallback


def get_data_prop(entity, prop_name: str):
    prop = getattr(onto, prop_name, None)
    if not prop:
        return None
    try:
        values = prop[entity]
    except ValueError as e:
        # Some literals in the ontology may have unknown datatypes that
        # owlready2 cannot convert to Python — log and skip the value.
        logging.getLogger(__name__).warning(
            "Could not read data property '%s' for %s: %s",
            prop_name,
            getattr(entity, "iri", str(entity)),
            e,
        )
        return None
    except Exception:
        # Unexpected errors — don't crash the whole request
        logging.getLogger(__name__).exception(
            "Unexpected error reading data property '%s'", prop_name
        )
        return None

    if not values:
        return None

    val = values[0]
    # Return the raw value; callers will coerce/convert as needed.
    try:
        return val
    except Exception:
        try:
            return str(val)
        except Exception:
            return None


def get_concept_code(entity) -> Optional[str]:
    val = get_data_prop(entity, "hasConceptCode")
    return str(val) if val is not None else None


def find_concept_by_code(code: str):
    if not hasattr(onto, "GeometricConcept"):
        return None
    for c in onto.GeometricConcept.instances():
        if get_concept_code(c) == code:
            return c
    return None


def concept_to_model(c) -> Concept:
    code = get_concept_code(c)
    difficulty = get_data_prop(c, "hasDifficultyLevel")
    desc = get_data_prop(c, "hasDescription")

    prereq_codes: List[str] = []
    if hasattr(onto, "hasPrerequisite"):
        for p in getattr(c, "hasPrerequisite", []):
            pc = get_concept_code(p)
            if pc:
                prereq_codes.append(pc)

    # Auto-mapping for images: by default image_key == code
    image_key = code

    # Normalize difficulty to an int if possible
    difficulty_int: Optional[int] = None
    if difficulty is not None:
        try:
            difficulty_int = int(difficulty)
        except (TypeError, ValueError):
            try:
                difficulty_int = int(str(difficulty))
            except Exception:
                difficulty_int = None

    return Concept(
        iri=c.iri,
        code=code,
        label=get_label(c),
        description=str(desc) if desc is not None else None,
        difficulty=difficulty_int,
        prerequisites=prereq_codes,
        image_key=image_key,
    )


# =========================
# API Endpoints
# =========================

@app.get("/concepts", response_model=List[Concept])
def list_concepts():
    if not hasattr(onto, "GeometricConcept"):
        return []
    return [concept_to_model(c) for c in onto.GeometricConcept.instances()]


@app.get("/concepts/{code}", response_model=Concept)
def get_concept(code: str):
    c = find_concept_by_code(code)
    if not c:
        raise HTTPException(status_code=404, detail="Concept not found")
    return concept_to_model(c)


@app.post("/next-concepts", response_model=List[Concept])
def suggest_next_concepts(req: NextConceptsRequest):
    """
    Recommend concepts whose prerequisites are all in mastered_concepts
    and which are not already mastered.
    """
    mastered = set(req.mastered_concepts)
    suggestions: List[Concept] = []

    if not hasattr(onto, "GeometricConcept"):
        return suggestions

    for c in onto.GeometricConcept.instances():
        code = get_concept_code(c)
        if not code or code in mastered:
            continue

        prereq_codes: List[str] = []
        if hasattr(onto, "hasPrerequisite"):
            for p in getattr(c, "hasPrerequisite", []):
                pc = get_concept_code(p)
                if pc:
                    prereq_codes.append(pc)

        if set(prereq_codes).issubset(mastered):
            suggestions.append(concept_to_model(c))

    suggestions.sort(key=lambda x: (x.difficulty or 999, x.label.lower()))
    return suggestions


@app.get("/problems", response_model=List[Problem])
def list_problems():
    problems: List[Problem] = []
    if not hasattr(onto, "Problem"):
        return problems

    for p in onto.Problem.instances():
        label = get_label(p)
        text = get_data_prop(p, "hasProblemText") or ""

        teaches_codes: List[str] = []
        if hasattr(onto, "teachesConcept"):
            for c in getattr(p, "teachesConcept", []):
                code = get_concept_code(c)
                if code:
                    teaches_codes.append(code)

        hint_codes: List[str] = []
        if hasattr(onto, "hasHint"):
            for c in getattr(p, "hasHint", []):
                code = get_concept_code(c)
                if code:
                    hint_codes.append(code)

        problems.append(
            Problem(
                iri=p.iri,
                label=label,
                text=str(text),
                teaches_concepts=teaches_codes,
                has_hint_concepts=hint_codes,
            )
        )

    return problems


@app.post("/check-answer", response_model=AnswerResult)
def check_answer(req: AnswerRequest):
    try:
        problem = default_world[req.problem_iri]
    except KeyError:
        raise HTTPException(status_code=404, detail="Problem not found")

    correct_answer = get_data_prop(problem, "hasCorrectAnswer")
    if correct_answer is None:
        return AnswerResult(
            correct=False,
            correct_answer=None,
            feedback="This problem does not have a stored correct answer.",
        )

    user_ans = req.answer.strip().lower()
    correct_norm = str(correct_answer).strip().lower()

    if user_ans == correct_norm:
        return AnswerResult(
            correct=True,
            correct_answer=str(correct_answer),
            feedback="Correct! Well done.",
        )
    else:
        return AnswerResult(
            correct=False,
            correct_answer=str(correct_answer),
            feedback="Not quite. Review the concept and try again.",
        )

