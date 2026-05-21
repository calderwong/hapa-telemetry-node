"""Database layer for telemetry node"""

import os
import json
import asyncio
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy import Column, String, Text, DateTime, Float, Integer, Boolean, JSON
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import select, delete, and_
from sqlalchemy import func

from .models import NodeInfo, NodeTelemetry, NodeStatus
from .artifact_paths import get_db_path

Base = declarative_base()


class NodeRecord(Base):
    __tablename__ = "nodes"
    
    node_id = Column(String, primary_key=True)
    service_type = Column(String)
    base_url = Column(String, nullable=False)
    display_name = Column(String)
    description = Column(Text)
    auth_required = Column(Boolean, default=True)
    token = Column(String)
    discovered_at = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)
    node_metadata = Column(JSON, default={})
    status = Column(String, default="unknown")


class TelemetryRecord(Base):
    __tablename__ = "telemetry"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    node_id = Column(String, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    status = Column(String)
    health_status = Column(String)
    cpu_percent = Column(Float)
    memory_mb = Column(Float)
    disk_usage_mb = Column(Float)
    queue_depth = Column(Integer)
    tasks_completed = Column(Integer)
    tasks_failed = Column(Integer)
    capabilities = Column(JSON)
    relationships = Column(JSON)
    raw_data = Column(JSON)


class Database:
    def __init__(self, db_path: str = "telemetry.db"):
        if db_path == "telemetry.db":
            db_path = os.environ.get("HAPA_TELEMETRY_DB_PATH", db_path)
        self.db_url = f"sqlite+aiosqlite:///{db_path}"
        self.engine = None
        self.async_session = None
        
    async def initialize(self):
        """Initialize database and create tables"""
        self.engine = create_async_engine(self.db_url, echo=False)
        self.async_session = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )
        
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    
    @asynccontextmanager
    async def get_session(self):
        """Get database session"""
        async with self.async_session() as session:
            yield session
    
    async def register_node(self, node_info: NodeInfo) -> NodeInfo:
        """Register or update a node"""
        async with self.get_session() as session:
            # Check if node exists
            stmt = select(NodeRecord).where(NodeRecord.node_id == node_info.node_id)
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()
            
            if existing:
                # Update existing node
                existing.base_url = node_info.base_url
                existing.last_seen = datetime.utcnow()
                existing.status = NodeStatus.ONLINE
                if node_info.display_name:
                    existing.display_name = node_info.display_name
                if node_info.description:
                    existing.description = node_info.description
                if node_info.token:
                    existing.token = node_info.token
                existing.node_metadata = node_info.metadata
            else:
                # Create new node
                node = NodeRecord(
                    node_id=node_info.node_id,
                    service_type=node_info.service_type,
                    base_url=node_info.base_url,
                    display_name=node_info.display_name,
                    description=node_info.description,
                    auth_required=node_info.auth_required,
                    token=node_info.token,
                    discovered_at=node_info.discovered_at,
                    last_seen=datetime.utcnow(),
                    node_metadata=node_info.metadata,
                    status=NodeStatus.ONLINE
                )
                session.add(node)
            
            await session.commit()
            return node_info
    
    async def get_node(self, node_id: str) -> Optional[NodeInfo]:
        """Get node by ID"""
        async with self.get_session() as session:
            stmt = select(NodeRecord).where(NodeRecord.node_id == node_id)
            result = await session.execute(stmt)
            record = result.scalar_one_or_none()
            
            if record:
                return NodeInfo(
                    node_id=record.node_id,
                    service_type=record.service_type,
                    base_url=record.base_url,
                    display_name=record.display_name,
                    description=record.description,
                    auth_required=record.auth_required,
                    token=record.token,
                    discovered_at=record.discovered_at,
                    last_seen=record.last_seen,
                    metadata=record.node_metadata or {}
                )
            return None
    
    async def list_nodes(self, active_only: bool = False) -> List[NodeInfo]:
        """List all nodes"""
        async with self.get_session() as session:
            stmt = select(NodeRecord).order_by(NodeRecord.node_id)
            
            if active_only:
                # Consider nodes active if seen in last 5 minutes
                cutoff = datetime.utcnow() - timedelta(minutes=5)
                stmt = stmt.where(NodeRecord.last_seen >= cutoff)
            
            result = await session.execute(stmt)
            records = result.scalars().all()
            
            return [
                NodeInfo(
                    node_id=r.node_id,
                    service_type=r.service_type,
                    base_url=r.base_url,
                    display_name=r.display_name,
                    description=r.description,
                    auth_required=r.auth_required,
                    token=r.token,
                    discovered_at=r.discovered_at,
                    last_seen=r.last_seen,
                    metadata=r.node_metadata or {}
                )
                for r in records
            ]
    
    async def record_telemetry(self, telemetry: NodeTelemetry):
        """Record telemetry data"""
        async with self.get_session() as session:
            metrics = telemetry.metrics.model_dump(mode="json") if telemetry.metrics else {}
            custom_metrics = metrics.get("custom") if isinstance(metrics.get("custom"), dict) else {}

            disk_usage_mb = custom_metrics.get("disk_usage_mb")
            if disk_usage_mb is None:
                # Prefer normalized disk metrics (disk_gb) when available
                disk_gb = metrics.get("disk_gb")
                if disk_gb is not None:
                    try:
                        disk_usage_mb = float(disk_gb) * 1024.0
                    except Exception:
                        disk_usage_mb = None

            tasks_completed = custom_metrics.get("tasks_completed")
            if tasks_completed is None:
                tasks_completed = metrics.get("queue_completed")

            tasks_failed = custom_metrics.get("tasks_failed")

            record = TelemetryRecord(
                node_id=telemetry.node_id,
                timestamp=telemetry.timestamp,
                status=telemetry.status.value if telemetry.status else None,
                health_status=telemetry.health.status.value if telemetry.health and telemetry.health.status else None,
                cpu_percent=metrics.get("cpu_percent"),
                memory_mb=metrics.get("memory_mb"),
                disk_usage_mb=disk_usage_mb,
                queue_depth=metrics.get("queue_depth"),
                tasks_completed=tasks_completed,
                tasks_failed=tasks_failed,
                capabilities=telemetry.capabilities.model_dump(mode="json") if telemetry.capabilities else None,
                relationships=telemetry.relationships.model_dump(mode="json") if telemetry.relationships else None,
                raw_data=telemetry.model_dump(mode="json")
            )
            session.add(record)
            
            # Update node last_seen
            stmt = select(NodeRecord).where(NodeRecord.node_id == telemetry.node_id)
            result = await session.execute(stmt)
            node = result.scalar_one_or_none()
            if node:
                node.last_seen = datetime.utcnow()
                node.status = telemetry.status.value if telemetry.status else None
            
            await session.commit()
    
    async def get_latest_telemetry(self, node_id: str) -> Optional[NodeTelemetry]:
        """Get latest telemetry for a node"""
        async with self.get_session() as session:
            stmt = (
                select(TelemetryRecord)
                .where(TelemetryRecord.node_id == node_id)
                .order_by(TelemetryRecord.timestamp.desc())
                .limit(1)
            )
            result = await session.execute(stmt)
            record = result.scalar_one_or_none()
            
            if record and record.raw_data:
                return NodeTelemetry(**record.raw_data)
            return None
    
    async def get_telemetry_history(
        self, 
        node_id: str, 
        hours: int = 1
    ) -> List[Dict[str, Any]]:
        """Get telemetry history for a node"""
        async with self.get_session() as session:
            cutoff = datetime.utcnow() - timedelta(hours=hours)
            stmt = (
                select(TelemetryRecord)
                .where(
                    and_(
                        TelemetryRecord.node_id == node_id,
                        TelemetryRecord.timestamp >= cutoff
                    )
                )
                .order_by(TelemetryRecord.timestamp.desc())
            )
            result = await session.execute(stmt)
            records = result.scalars().all()
            
            return [r.raw_data for r in records if r.raw_data]
    
    async def mark_node_offline(self, node_id: str):
        """Mark a node as offline"""
        async with self.get_session() as session:
            stmt = select(NodeRecord).where(NodeRecord.node_id == node_id)
            result = await session.execute(stmt)
            node = result.scalar_one_or_none()
            
            if node:
                node.status = NodeStatus.OFFLINE
                await session.commit()
    
    async def cleanup_old_telemetry(self, days: int = 7):
        """Clean up old telemetry records"""
        async with self.get_session() as session:
            cutoff = datetime.utcnow() - timedelta(days=days)
            stmt = delete(TelemetryRecord).where(
                TelemetryRecord.timestamp < cutoff
            )
            await session.execute(stmt)
            await session.commit()
    
    async def close(self):
        """Close database connection"""
        if self.engine:
            await self.engine.dispose()
