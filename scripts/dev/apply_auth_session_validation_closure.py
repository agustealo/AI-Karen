from __future__ import annotations

from pathlib import Path

AUTH_SERVICE = Path("src/ai_karen_engine/services/auth/auth_service.py")
AUTH_ROUTE = Path("src/ai_karen_engine/api_routes/auth/auth.py")


def patch_auth_service() -> None:
    source = AUTH_SERVICE.read_text(encoding="utf-8")

    start = source.index("    async def validate_session(\n")
    end = source.index("    async def list_sessions(\n", start)
    replacement = '''    async def validate_session(
        self, session_token: str, ip_address: str = "unknown", user_agent: str = ""
    ) -> Optional[UserAccount]:
        """Validate a session against the durable database authority.

        Session validation fails closed when the database is unavailable.
        Process-local caches are optimization only and can never resurrect
        a revoked or disabled session.
        """
        if not self._initialized:
            await self.initialize()

        try:
            async with self._session_scope() as db_session:
                result = await db_session.execute(
                    select(AuthSession).where(
                        AuthSession.access_token == session_token,
                        AuthSession.is_active,
                    )
                )
                db_auth_session = result.scalar_one_or_none()
                if not db_auth_session:
                    return None

                try:
                    payload = jwt.decode(
                        session_token,
                        self.config.jwt_secret_key,
                        algorithms=[self.config.jwt_algorithm],
                        options={"verify_aud": False},
                    )
                    if payload.get("exp", 0) < time.time():
                        return None
                except Exception:
                    return None

                if db_auth_session.device_fingerprint:
                    current_fingerprint = self._generate_device_fingerprint(
                        user_agent, ip_address
                    )
                    if db_auth_session.device_fingerprint != current_fingerprint:
                        logger.warning(
                            "Device fingerprint mismatch for session %s",
                            db_auth_session.session_token,
                        )

                user_result = await db_session.execute(
                    select(AuthUser).where(AuthUser.user_id == db_auth_session.user_id)
                )
                auth_user = user_result.scalar_one_or_none()
                if not auth_user or not auth_user.is_active:
                    db_auth_session.is_active = False
                    db_auth_session.invalidated_at = datetime.utcnow()
                    db_auth_session.invalidation_reason = "user_inactive"
                    await db_session.flush()
                    return None

                db_auth_session.last_accessed = datetime.utcnow()
                await db_session.flush()

                user = self._build_user_account(auth_user)
                self._user_cache[user.id] = user
                return user
        except Exception as exc:
            logger.error(
                "Database session validation failed; rejecting session: %s", exc
            )
            return None

'''
    source = source[:start] + replacement + source[end:]

    if "    async def change_user_password(\n" in source:
        raise RuntimeError("change_user_password already exists; refusing duplicate")

    marker = "    def _hash_password(self, password: str) -> str:\n"
    insert_at = source.index(marker)
    password_method = '''    async def change_user_password(
        self,
        user_id: str,
        current_password: str,
        new_password: str,
    ) -> Optional[str]:
        """Change a user's password and revoke every active session.

        Password mutation and durable session revocation occur in the same
        database transaction. A successful change therefore requires the
        user to authenticate again on every worker and device.
        """
        if not self._initialized:
            await self.initialize()

        password_error = self._validate_password(new_password)
        if password_error:
            return password_error
        if current_password == new_password:
            return "New password must be different from current password"

        try:
            user_uuid = uuid.UUID(str(user_id))
        except ValueError:
            return "Invalid user ID"

        try:
            async with self._session_scope() as session:
                result = await session.execute(
                    select(AuthUser)
                    .where(AuthUser.user_id == user_uuid)
                    .with_for_update()
                )
                auth_user = result.scalar_one_or_none()
                if not auth_user:
                    return "User not found"

                if not self._verify_password(current_password, auth_user.password_hash):
                    await self._emit_audit_event(
                        action="auth.password.change",
                        actor_user_id=user_id,
                        target_user_id=user_id,
                        status="denied",
                        reason_code="current_password_mismatch",
                    )
                    return "Current password is incorrect"

                auth_user.password_hash = self._hash_password(new_password)
                auth_user.updated_at = datetime.utcnow()

                sessions_result = await session.execute(
                    select(AuthSession)
                    .where(
                        AuthSession.user_id == user_uuid,
                        AuthSession.is_active,
                    )
                    .with_for_update()
                )
                active_sessions = sessions_result.scalars().all()
                now = datetime.utcnow()
                for db_session in active_sessions:
                    db_session.is_active = False
                    db_session.invalidated_at = now
                    db_session.invalidation_reason = "password_changed"

                await session.flush()

                self._user_cache.pop(user_id, None)
                for cached_session in self._active_sessions.values():
                    if cached_session.user_id == user_id:
                        cached_session.is_active = False

                await self._emit_audit_event(
                    action="auth.password.change",
                    actor_user_id=user_id,
                    target_user_id=user_id,
                    status="success",
                    reason_code="password_changed",
                    metadata={"revoked_session_count": len(active_sessions)},
                )
                return None
        except Exception as exc:
            logger.error("Password change failed for user %s: %s", user_id, exc)
            return "Password update failed"

'''
    source = source[:insert_at] + password_method + source[insert_at:]
    AUTH_SERVICE.write_text(source, encoding="utf-8")


def patch_route() -> None:
    source = AUTH_ROUTE.read_text(encoding="utf-8")
    old = '    return {"detail": "Password updated successfully"}\n'
    new = '''    response = JSONResponse(
        content={"detail": "Password updated successfully; sign in again"}
    )
    response.delete_cookie("kari_session", path="/")
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
    return response
'''
    if old not in source:
        raise RuntimeError("change-password route marker not found")
    AUTH_ROUTE.write_text(source.replace(old, new, 1), encoding="utf-8")


if __name__ == "__main__":
    patch_auth_service()
    patch_route()
