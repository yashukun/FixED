from datetime import datetime, timedelta
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()


class Metric(BaseModel):
    label: str
    value: int


class FocusItem(BaseModel):
    title: str
    time: str
    type: str


class DashboardOverviewResponse(BaseModel):
    source: str
    metrics: list[Metric]
    todayFocus: list[FocusItem]


class BookItem(BaseModel):
    id: str
    title: str
    subject: str
    status: str
    lastOpened: str


class LearnBooksResponse(BaseModel):
    source: str
    teacherUploaded: list[BookItem]
    studentUploaded: list[BookItem]


class SubjectItem(BaseModel):
    id: str
    name: str
    teacher: str
    pendingAssignments: int
    progress: int


class LearnSubjectsResponse(BaseModel):
    source: str
    subjects: list[SubjectItem]


class UpcomingEvent(BaseModel):
    id: str
    title: str
    when: str
    subject: str
    kind: str


class UpcomingEventsResponse(BaseModel):
    source: str
    events: list[UpcomingEvent]


class DashboardNavResponse(BaseModel):
    source: str
    student: dict
    sections: list[dict]


@app.get("/health")
def health():
    return {"status": "ok", "service": "gateway"}


@app.get("/dashboard/nav", response_model=DashboardNavResponse)
def dashboard_nav():
    return {
        "source": "mock",
        "student": {
            "id": "student-001",
            "name": "Aarav Sharma",
            "grade": "Class 10",
        },
        "sections": [
            {"name": "Dashboard", "path": "/"},
            {"name": "Learn / Books", "path": "/learn/books"},
            {"name": "Learn / Subjects", "path": "/learn/subjects"},
            {"name": "Upcoming", "path": "/upcoming"},
        ],
    }


@app.get("/dashboard/overview", response_model=DashboardOverviewResponse)
def dashboard_overview():
    return {
        "source": "mock",
        "metrics": [
            {"label": "Assigned Subjects", "value": 5},
            {"label": "Active Books", "value": 12},
            {"label": "Pending Assignments", "value": 3},
            {"label": "Tests This Week", "value": 2},
        ],
        "todayFocus": [
            {"title": "Physics chapter recap", "time": "4:00 PM", "type": "study"},
            {"title": "Math weekly test prep", "time": "6:00 PM", "type": "test"},
            {"title": "English viva practice", "time": "8:00 PM", "type": "viva"},
        ],
    }


@app.get("/learn/books", response_model=LearnBooksResponse)
def learn_books():
    now = datetime.utcnow()
    teacher_books = [
        {
            "id": "book-teacher-1",
            "title": "Class 10 Physics Essentials",
            "subject": "Physics",
            "status": "ready",
            "lastOpened": (now - timedelta(days=1)).strftime("%Y-%m-%d"),
        },
        {
            "id": "book-teacher-2",
            "title": "Modern World History",
            "subject": "History",
            "status": "ready",
            "lastOpened": (now - timedelta(days=3)).strftime("%Y-%m-%d"),
        },
    ]
    student_books = [
        {
            "id": "book-student-1",
            "title": "Notes - Algebra Revision",
            "subject": "Math",
            "status": "ready",
            "lastOpened": (now - timedelta(hours=8)).strftime("%Y-%m-%d"),
        },
        {
            "id": "book-student-2",
            "title": "Biology Practical Book",
            "subject": "Biology",
            "status": "processing",
            "lastOpened": (now - timedelta(days=2)).strftime("%Y-%m-%d"),
        },
    ]
    return {"source": "mock", "teacherUploaded": teacher_books, "studentUploaded": student_books}


@app.get("/learn/subjects", response_model=LearnSubjectsResponse)
def learn_subjects():
    return {
        "source": "mock",
        "subjects": [
            {"id": "sub-1", "name": "Physics", "teacher": "Ms. Nair", "pendingAssignments": 1, "progress": 74},
            {"id": "sub-2", "name": "Mathematics", "teacher": "Mr. Jain", "pendingAssignments": 2, "progress": 68},
            {"id": "sub-3", "name": "English", "teacher": "Ms. Kapoor", "pendingAssignments": 0, "progress": 81},
            {"id": "sub-4", "name": "Biology", "teacher": "Mr. Iqbal", "pendingAssignments": 1, "progress": 59},
            {"id": "sub-5", "name": "History", "teacher": "Ms. Das", "pendingAssignments": 0, "progress": 88},
        ],
    }


@app.get("/upcoming/events", response_model=UpcomingEventsResponse)
def upcoming_events():
    return {
        "source": "mock",
        "events": [
            {
                "id": "event-1",
                "title": "Math Scheduled Test",
                "when": "Friday, 10:30 AM",
                "subject": "Mathematics",
                "kind": "test",
            },
            {
                "id": "event-2",
                "title": "English Mock Viva",
                "when": "Monday, 3:00 PM",
                "subject": "English",
                "kind": "viva",
            },
        ],
    }
