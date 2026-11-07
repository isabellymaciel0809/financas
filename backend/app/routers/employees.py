from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Employee
from app.schemas import EmployeeIn, EmployeeOut

router = APIRouter(prefix="/employees", tags=["funcionários"])


@router.get("", response_model=list[EmployeeOut])
def list_employees(db: Session = Depends(get_db)):
    return db.scalars(select(Employee).order_by(Employee.active.desc(), Employee.name)).all()


@router.post("", response_model=EmployeeOut, status_code=status.HTTP_201_CREATED)
def create_employee(payload: EmployeeIn, db: Session = Depends(get_db)):
    employee = Employee(**payload.model_dump())
    db.add(employee)
    db.commit()
    db.refresh(employee)
    return employee


@router.put("/{employee_id}", response_model=EmployeeOut)
def update_employee(employee_id: int, payload: EmployeeIn, db: Session = Depends(get_db)):
    """Funcionário que saiu é desativado, não apagado: os lançamentos antigos continuam ligados."""
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Funcionário não encontrado.")
    for key, value in payload.model_dump().items():
        setattr(employee, key, value)
    db.commit()
    db.refresh(employee)
    return employee
