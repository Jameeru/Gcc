"""
Data access repositories for the GCC Research Intelligence Platform.

This module provides repository classes for database operations with proper
error handling, transaction management, and query optimization.
"""

from datetime import datetime, timezone
from typing import List, Optional, Dict, Any, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import desc, asc, and_, or_, func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from .schemas import User, ResearchResult, ProcessingSession, ApiSetting
from ..utils.crypto import get_secret_box, DecryptionError


class BaseRepository:
    """Base repository with common database operations."""
    
    def __init__(self, session: Session):
        """
        Initialize repository with database session.
        
        Args:
            session: SQLAlchemy session for database operations.
        """
        self.session = session
    
    def commit(self) -> None:
        """Commit current transaction."""
        self.session.commit()
    
    def rollback(self) -> None:
        """Rollback current transaction."""
        self.session.rollback()
    
    def refresh(self, instance) -> None:
        """Refresh instance from database."""
        self.session.refresh(instance)


class UserRepository(BaseRepository):
    """Repository for User model operations."""
    
    def create_user(self, passcode: str) -> User:
        """
        Create a new user with the given passcode.
        
        Args:
            passcode: Hashed passcode for authentication.
            
        Returns:
            Created User instance.
            
        Raises:
            IntegrityError: If passcode already exists.
        """
        user = User(passcode=passcode)
        self.session.add(user)
        self.session.flush()  # Flush to get ID without committing
        return user
    
    def get_user_by_id(self, user_id: int) -> Optional[User]:
        """
        Get user by ID.
        
        Args:
            user_id: User ID to search for.
            
        Returns:
            User instance if found, None otherwise.
        """
        return self.session.query(User).filter(User.id == user_id).first()
    
    def get_user_by_passcode(self, passcode: str) -> Optional[User]:
        """
        Get user by passcode for authentication.
        
        Args:
            passcode: Passcode to search for.
            
        Returns:
            User instance if found, None otherwise.
        """
        return self.session.query(User).filter(
            User.passcode == passcode,
            User.is_active == True
        ).first()
    
    def update_last_login(self, user_id: int) -> bool:
        """
        Update user's last login timestamp.
        
        Args:
            user_id: ID of user to update.
            
        Returns:
            True if update successful, False otherwise.
        """
        try:
            updated_rows = self.session.query(User).filter(
                User.id == user_id
            ).update({
                User.last_login: datetime.now(timezone.utc)
            })
            return updated_rows > 0
        except SQLAlchemyError:
            return False
    
    def deactivate_user(self, user_id: int) -> bool:
        """
        Deactivate a user account.
        
        Args:
            user_id: ID of user to deactivate.
            
        Returns:
            True if deactivation successful, False otherwise.
        """
        try:
            updated_rows = self.session.query(User).filter(
                User.id == user_id
            ).update({User.is_active: False})
            return updated_rows > 0
        except SQLAlchemyError:
            return False
    
    def get_all_active_users(self) -> List[User]:
        """
        Get all active users.
        
        Returns:
            List of active User instances.
        """
        return self.session.query(User).filter(
            User.is_active == True
        ).order_by(User.created_at.desc()).all()


class ResearchResultRepository(BaseRepository):
    """Repository for ResearchResult model operations."""
    
    def create_research_result(self, 
                             normalized_key: str,
                             company_name: str,
                             company_domain: Optional[str] = None,
                             gcc_presence: Optional[bool] = None,
                             gcc_location: Optional[str] = None,
                             suitability_score: Optional[int] = None,
                             business_pain_points: Optional[str] = None,
                             expansion_indicators: Optional[str] = None,
                             hiring_signals: Optional[str] = None,
                             research_summary: Optional[str] = None,
                             research_metadata: Optional[Dict[str, Any]] = None) -> ResearchResult:
        """
        Create a new research result.
        
        Args:
            normalized_key: Unique normalized cache key.
            company_name: Company name.
            company_domain: Company domain (optional).
            gcc_presence: Whether company has GCC in India.
            gcc_location: Location of GCC if present.
            suitability_score: GCC suitability score (1-10).
            business_pain_points: Identified business challenges.
            expansion_indicators: Signs of expansion potential.
            hiring_signals: Hiring activity indicators.
            research_summary: Summary of research findings.
            research_metadata: Additional metadata as JSON.
            
        Returns:
            Created ResearchResult instance.
            
        Raises:
            IntegrityError: If normalized_key already exists.
            ValueError: If suitability_score is not between 1-10.
        """
        if suitability_score is not None and not (1 <= suitability_score <= 10):
            raise ValueError("Suitability score must be between 1 and 10")
        
        research_result = ResearchResult(
            normalized_key=normalized_key,
            company_name=company_name,
            company_domain=company_domain,
            gcc_presence=gcc_presence,
            gcc_location=gcc_location,
            suitability_score=suitability_score,
            business_pain_points=business_pain_points,
            expansion_indicators=expansion_indicators,
            hiring_signals=hiring_signals,
            research_summary=research_summary,
            research_metadata=research_metadata
        )
        
        self.session.add(research_result)
        self.session.flush()
        return research_result
    
    def get_by_normalized_key(self, normalized_key: str) -> Optional[ResearchResult]:
        """
        Get research result by normalized key (cache lookup).
        
        Args:
            normalized_key: Normalized cache key to search for.
            
        Returns:
            ResearchResult instance if found, None otherwise.
        """
        return self.session.query(ResearchResult).filter(
            ResearchResult.normalized_key == normalized_key
        ).first()
    
    def get_by_id(self, result_id: int) -> Optional[ResearchResult]:
        """
        Get research result by ID.
        
        Args:
            result_id: Research result ID.
            
        Returns:
            ResearchResult instance if found, None otherwise.
        """
        return self.session.query(ResearchResult).filter(
            ResearchResult.id == result_id
        ).first()
    
    def search_results(self, 
                      search_term: Optional[str] = None,
                      gcc_presence: Optional[bool] = None,
                      min_suitability_score: Optional[int] = None,
                      max_suitability_score: Optional[int] = None,
                      start_date: Optional[datetime] = None,
                      end_date: Optional[datetime] = None,
                      limit: Optional[int] = None,
                      offset: int = 0,
                      order_by: str = 'created_at',
                      order_direction: str = 'desc') -> Tuple[List[ResearchResult], int]:
        """
        Search and filter research results with pagination.
        
        Args:
            search_term: Search term for company name or domain.
            gcc_presence: Filter by GCC presence status.
            min_suitability_score: Minimum suitability score filter.
            max_suitability_score: Maximum suitability score filter.
            start_date: Filter results created after this date.
            end_date: Filter results created before this date.
            limit: Maximum number of results to return.
            offset: Number of results to skip for pagination.
            order_by: Column to order by ('created_at', 'company_name', 'suitability_score').
            order_direction: Order direction ('asc' or 'desc').
            
        Returns:
            Tuple of (results list, total count).
        """
        query = self.session.query(ResearchResult)
        
        # Apply filters
        conditions = []
        
        if search_term:
            search_pattern = f"%{search_term}%"
            conditions.append(
                or_(
                    ResearchResult.company_name.ilike(search_pattern),
                    ResearchResult.company_domain.ilike(search_pattern)
                )
            )
        
        if gcc_presence is not None:
            conditions.append(ResearchResult.gcc_presence == gcc_presence)
        
        if min_suitability_score is not None:
            conditions.append(ResearchResult.suitability_score >= min_suitability_score)
        
        if max_suitability_score is not None:
            conditions.append(ResearchResult.suitability_score <= max_suitability_score)
        
        if start_date:
            conditions.append(ResearchResult.created_at >= start_date)
        
        if end_date:
            conditions.append(ResearchResult.created_at <= end_date)
        
        if conditions:
            query = query.filter(and_(*conditions))
        
        # Get total count before applying pagination
        total_count = query.count()
        
        # Apply ordering
        order_column = getattr(ResearchResult, order_by, ResearchResult.created_at)
        if order_direction.lower() == 'desc':
            query = query.order_by(desc(order_column))
        else:
            query = query.order_by(asc(order_column))
        
        # Apply pagination
        if offset > 0:
            query = query.offset(offset)
        if limit:
            query = query.limit(limit)
        
        results = query.all()
        return results, total_count
    
    def get_cache_statistics(self) -> Dict[str, Any]:
        """
        Get cache statistics for monitoring.
        
        Returns:
            Dictionary with cache statistics.
        """
        total_results = self.session.query(func.count(ResearchResult.id)).scalar() or 0
        
        results_with_gcc = self.session.query(func.count(ResearchResult.id)).filter(
            ResearchResult.gcc_presence == True
        ).scalar() or 0
        
        avg_suitability = self.session.query(func.avg(ResearchResult.suitability_score)).filter(
            ResearchResult.suitability_score.is_not(None)
        ).scalar() or 0
        
        return {
            "total_cached_results": total_results,
            "results_with_gcc": results_with_gcc,
            "gcc_presence_rate": (results_with_gcc / total_results * 100) if total_results > 0 else 0,
            "average_suitability_score": round(float(avg_suitability), 2),
            "cache_size_mb": 0  # Could be calculated from actual data size
        }


class ProcessingSessionRepository(BaseRepository):
    """Repository for ProcessingSession model operations."""
    
    def create_session(self, session_id: str, total_companies: int) -> ProcessingSession:
        """
        Create a new processing session.
        
        Args:
            session_id: Unique session identifier.
            total_companies: Total number of companies to process.
            
        Returns:
            Created ProcessingSession instance.
        """
        processing_session = ProcessingSession(
            session_id=session_id,
            total_companies=total_companies
        )
        
        self.session.add(processing_session)
        self.session.flush()
        return processing_session
    
    def get_by_session_id(self, session_id: str) -> Optional[ProcessingSession]:
        """
        Get processing session by session ID.
        
        Args:
            session_id: Session ID to search for.
            
        Returns:
            ProcessingSession instance if found, None otherwise.
        """
        return self.session.query(ProcessingSession).filter(
            ProcessingSession.session_id == session_id
        ).first()
    
    def update_progress(self, 
                       session_id: str,
                       processed_companies: Optional[int] = None,
                       cache_hits: Optional[int] = None,
                       errors: Optional[int] = None) -> bool:
        """
        Update processing session progress.
        
        Args:
            session_id: Session ID to update.
            processed_companies: Number of processed companies.
            cache_hits: Number of cache hits.
            errors: Number of errors encountered.
            
        Returns:
            True if update successful, False otherwise.
        """
        try:
            update_data = {}
            if processed_companies is not None:
                update_data[ProcessingSession.processed_companies] = processed_companies
            if cache_hits is not None:
                update_data[ProcessingSession.cache_hits] = cache_hits
            if errors is not None:
                update_data[ProcessingSession.errors] = errors
            
            if update_data:
                updated_rows = self.session.query(ProcessingSession).filter(
                    ProcessingSession.session_id == session_id
                ).update(update_data)
                return updated_rows > 0
            return False
        except SQLAlchemyError:
            return False
    
    def complete_session(self, session_id: str, status: str = 'completed') -> bool:
        """
        Mark processing session as completed.
        
        Args:
            session_id: Session ID to complete.
            status: Final status ('completed', 'stopped', 'error').
            
        Returns:
            True if completion successful, False otherwise.
        """
        try:
            updated_rows = self.session.query(ProcessingSession).filter(
                ProcessingSession.session_id == session_id
            ).update({
                ProcessingSession.status: status,
                ProcessingSession.completed_at: datetime.now(timezone.utc)
            })
            return updated_rows > 0
        except SQLAlchemyError:
            return False
    
    def get_active_sessions(self) -> List[ProcessingSession]:
        """
        Get all active (running) processing sessions.
        
        Returns:
            List of active ProcessingSession instances.
        """
        return self.session.query(ProcessingSession).filter(
            ProcessingSession.status == 'running'
        ).order_by(ProcessingSession.created_at.desc()).all()
    
    def get_recent_sessions(self, limit: int = 10) -> List[ProcessingSession]:
        """
        Get recent processing sessions.
        
        Args:
            limit: Maximum number of sessions to return.
            
        Returns:
            List of recent ProcessingSession instances.
        """
        return self.session.query(ProcessingSession).order_by(
            ProcessingSession.created_at.desc()
        ).limit(limit).all()


class ApiSettingsRepository(BaseRepository):
    """
    Repository for ApiSetting model operations.

    Transparently encrypts on write and decrypts on read, so callers
    (the Settings UI, the key-resolution layer) only ever see plaintext
    API keys -- the encrypted_value column is an implementation detail
    of this repository.
    """

    def get_plaintext(self, setting_key: str) -> Optional[str]:
        """
        Get the decrypted value for a setting key.

        Args:
            setting_key: e.g. 'openai_api_key', 'gemini_api_key_1'.

        Returns:
            The decrypted plaintext value, or None if not set.

        Raises:
            DecryptionError: If the stored value can't be decrypted with
                the current SETTINGS_ENCRYPTION_KEY (e.g. the key rotated).
        """
        setting = self.session.query(ApiSetting).filter(
            ApiSetting.setting_key == setting_key
        ).first()
        if setting is None:
            return None
        return get_secret_box().decrypt(setting.encrypted_value)

    def get_all_plaintext(self, setting_keys: List[str]) -> Dict[str, Optional[str]]:
        """
        Get decrypted values for several setting keys at once.

        Any individual key that fails to decrypt is reported as None rather
        than aborting the whole batch, so one corrupted/rotated-key entry
        doesn't take down the rest of the Settings UI.

        Args:
            setting_keys: List of setting keys to fetch.

        Returns:
            Dict mapping each requested setting_key to its plaintext value
            (None if unset or undecryptable).
        """
        rows = self.session.query(ApiSetting).filter(
            ApiSetting.setting_key.in_(setting_keys)
        ).all()
        by_key = {row.setting_key: row for row in rows}

        result: Dict[str, Optional[str]] = {}
        secret_box = get_secret_box()
        for key in setting_keys:
            row = by_key.get(key)
            if row is None:
                result[key] = None
                continue
            try:
                result[key] = secret_box.decrypt(row.encrypted_value)
            except DecryptionError:
                result[key] = None
        return result

    def set_plaintext(
        self, setting_key: str, plaintext_value: str, updated_by: Optional[str] = None
    ) -> ApiSetting:
        """
        Encrypt and upsert a setting value.

        Args:
            setting_key: e.g. 'openai_api_key', 'gemini_api_key_1'.
            plaintext_value: The raw secret to store (will be encrypted).
            updated_by: Optional identifier (e.g. user id) of who made the
                change, for audit purposes.

        Returns:
            The created or updated ApiSetting instance.

        Raises:
            ValueError: If plaintext_value is empty.
        """
        encrypted_value = get_secret_box().encrypt(plaintext_value)

        setting = self.session.query(ApiSetting).filter(
            ApiSetting.setting_key == setting_key
        ).first()

        if setting is None:
            setting = ApiSetting(
                setting_key=setting_key,
                encrypted_value=encrypted_value,
                updated_by=updated_by,
            )
            self.session.add(setting)
        else:
            setting.encrypted_value = encrypted_value
            setting.updated_by = updated_by
            setting.updated_at = datetime.now(timezone.utc)

        self.session.flush()
        return setting

    def delete_setting(self, setting_key: str) -> bool:
        """
        Remove a stored setting (e.g. to fall back to the env var default).

        Args:
            setting_key: Setting key to remove.

        Returns:
            True if a row was deleted, False if no such setting existed.
        """
        deleted_rows = self.session.query(ApiSetting).filter(
            ApiSetting.setting_key == setting_key
        ).delete()
        return deleted_rows > 0

    def is_set(self, setting_key: str) -> bool:
        """
        Check whether a setting has a stored (DB) value, without decrypting it.

        Useful for the Settings UI to show "configured" status without
        needing the actual key value.

        Args:
            setting_key: Setting key to check.

        Returns:
            True if a row exists for this setting_key.
        """
        return self.session.query(ApiSetting).filter(
            ApiSetting.setting_key == setting_key
        ).first() is not None