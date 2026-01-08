"""
SQLAlchemy models for X-Ray API
"""

import uuid
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Pipeline(db.Model):
    """A type of workflow (e.g., 'competitor_selection')"""
    __tablename__ = 'pipelines'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(255), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    runs = db.relationship('Run', backref='pipeline', lazy='dynamic')
    
    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


class Run(db.Model):
    """Single execution of a pipeline"""
    __tablename__ = 'runs'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    pipeline_id = db.Column(db.String(36), db.ForeignKey('pipelines.id'), nullable=False)
    status = db.Column(db.String(50), default='pending')
    run_metadata = db.Column(db.JSON, nullable=True)
    analysis_result = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    steps = db.relationship('Step', backref='run', lazy='dynamic', order_by='Step.step_order')
    
    def to_dict(self, include_steps=False):
        result = {
            "id": self.id,
            "pipeline_id": self.pipeline_id,
            "pipeline_name": self.pipeline.name if self.pipeline else None,
            "status": self.status,
            "metadata": self.run_metadata,
            "analysis_result": self.analysis_result,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }
        if include_steps:
            result["steps"] = [step.to_dict() for step in self.steps.order_by(Step.step_order)]
        return result


class Step(db.Model):
    """Individual step within a run"""
    __tablename__ = 'steps'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id = db.Column(db.String(36), db.ForeignKey('runs.id'), nullable=False)
    step_name = db.Column(db.String(255), nullable=False)
    step_order = db.Column(db.Integer, nullable=False)
    inputs = db.Column(db.JSON, nullable=True)
    outputs = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            "id": self.id,
            "run_id": self.run_id,
            "step_name": self.step_name,
            "step_order": self.step_order,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }
