# Geometry ITS Backend

This is a FastAPI backend for the Geometry Intelligent Tutoring System (ITS).

## Features

- Serves concepts and problems from an OWL ontology
- Teacher model and endpoints (in-memory)
- CORS enabled for frontend integration

## Requirements

- Python 3.8+
- FastAPI
- Uvicorn
- Owlready2
- Pydantic

## Setup

1. (Recommended) Create and activate a virtual environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```
2. Install dependencies:
   ```bash
   pip install fastapi uvicorn owlready2 pydantic
   ```
3. Place your ontology file as `geometry-its.owl` in the project root.

## Running the Server

```bash
uvicorn main:app --reload --port 8000
```

## API Endpoints

### Concepts

- `GET /concepts` — List all concepts
- `GET /concepts/{code}` — Get concept by code

### Problems

- `GET /problems` — List all problems
- `POST /check-answer` — Check answer for a problem

### Teachers

- `GET /teachers` — List all teachers
- `POST /teachers` — Create a teacher
- `GET /teachers/{teacher_id}` — Get teacher by ID

## Example: Create a Teacher

```bash
curl -X POST http://localhost:8000/teachers \
  -H "Content-Type: application/json" \
  -d '{"id": "", "name": "Jane Doe", "email": "jane@example.com", "subject": "Geometry", "bio": "Experienced geometry teacher"}'
```

## CORS

CORS is enabled for `http://localhost:3000` and `http://127.0.0.1:3000` for frontend integration.

## License

MIT
