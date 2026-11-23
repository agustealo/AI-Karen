        # Deleting/archiving the canonical file must not strand a still-live
        # author-attested consent or its dependent delegated grants.
        await raw.execute(
            "UPDATE public.files SET deleted_at=clock_timestamp() "
            "WHERE file_id=$1", str(artifact),
        )
        # Revoke current source voluntarily first; a wrong digest remains
        # denied without altering the live receipt.
        assert await issuer.revoke_first_party(
            **scope, correlation_id="wrong-source-revoke",
            request=bearer_request, expected_source_sha256="b" * 64,
        ) is False
        assert await issuer.revoke_first_party(
            **scope, correlation_id="author-revoke", request=bearer_request,
            expected_source_sha256=digest,
        ) is True
        assert await issuer.verify_current(**scope) is None
        # Mutating an already-revoked source cannot reactivate old rights.
        await raw.execute(
            "UPDATE public.files SET deleted_at=clock_timestamp() "
            "WHERE file_id=$1", str(artifact),
        )
        assert await issuer.verify_current(**scope) is None
        with pytest.raises(asyncpg.PostgresError):
            await scoped(
                owner, tenant,
                "UPDATE public.writing_style_document_consents "
                "SET revoked_at=NULL WHERE receipt_id=$1",
                receipt,
            )
        assert await raw.fetchval(
            "SELECT revoked_at IS NOT NULL "
            "FROM public.writing_style_document_consents WHERE receipt_id=$1",
            receipt,
        )
        assert await raw.fetchval(
            "SELECT state FROM public.writing_style_profiles "
            "WHERE tenant_id=$1 AND profile_id=$2", tenant, profile,
        ) == "revoked"
        assert await raw.fetchval(
            "SELECT revoked_at IS NOT NULL FROM public.writing_style_grants "
            "WHERE tenant_id=$1 AND profile_id=$2 AND actor_id=$3",
            tenant, profile, other_actor,
        ) is True
        # Prove the actual delegated-use runtime owner denies the same
        # previously granted actor and published revision after revocation.
        delegated_request = KariSignatureRequest(
            tenant_id=str(tenant),
            actor_id=str(other_actor),
            profile_id=str(profile),
            purpose="draft_email",
            correlation_id="post-revocation-use-denied",
        )
        published_revision = KariSignatureRevision(
            tenant_id=str(tenant),
            profile_id=str(profile),
            revision_id=str(revision),
            revision_number=1,
            state="published",
            approved_expression={"tone": "direct"},
            content_digest="b" * 64,
        )
        delegated_owner = WritingStyleProfileRepository(
            client_factory=TrustedTestClient,
        )
        assert await delegated_owner.read_current_published(
            request=delegated_request,
        ) is None
        assert await delegated_owner.authorize_use(
            request=delegated_request, revision=published_revision,
        ) is False

        # P2 regression: an author can revoke consent while the profile is
        # still draft, including after evidence has been registered. The
        # database must prevent both later publication and direct SQL grants.
        draft_profile = uuid.uuid4()
        draft_artifact = uuid.uuid4()
        draft_receipt = uuid.uuid4()
        draft_sample = uuid.uuid4()
        draft_revision = uuid.uuid4()
        await raw.execute(
            "INSERT INTO public.writing_style_profiles "
            "(tenant_id,profile_id,owner_actor_id,kind,label) "
            "VALUES ($1,$2,$3,'personal','Pending author document')",
            tenant, draft_profile, owner,
        )
        await raw.execute(
            "INSERT INTO public.files "
            "(file_id,tenant_id,owner_user_id,name,mime_type,bytes,sha256) "
            "VALUES ($1,$2,$3,'pending.txt','text/plain',10,$4)",
            str(draft_artifact), str(tenant), owner, digest,
        )
        await scoped(
            owner, tenant,
            "INSERT INTO public.writing_style_document_consents "
            "(tenant_id,profile_id,owner_actor_id,artifact_id,author_actor_id,"
            "source_sha256,receipt_id,analysis_allowed,style_use_allowed,"
            "author_attested,expires_at,correlation_id) "
            "VALUES ($1,$2,$3,$4,$3,$5,$6,true,true,true,"
            "clock_timestamp()+interval '1 day','draft-author-attested')",
            tenant, draft_profile, owner, draft_artifact, digest, draft_receipt,
        )
        await raw.execute(
            "INSERT INTO public.writing_style_sample_evidence "
            "(tenant_id,profile_id,owner_actor_id,sample_id,source_type,"
            "source_id,source_author_id,consent_receipt_id,analysis_allowed,"
            "style_use_allowed,consent_expires_at) "
            "VALUES ($1,$2,$3,$4,'document',$5,$3,$6,true,true,"
            "clock_timestamp()+interval '1 day')",
            tenant, draft_profile, owner, draft_sample,
            draft_artifact, draft_receipt,
        )
        assert await raw.fetchval(
            "SELECT state FROM public.writing_style_profiles "
            "WHERE tenant_id=$1 AND profile_id=$2",
            tenant, draft_profile,
        ) == "draft"
        await scoped(
            owner, tenant,
            "UPDATE public.writing_style_document_consents "
            "SET revoked_at=clock_timestamp() "
            "WHERE tenant_id=$1 AND profile_id=$2 AND receipt_id=$3",
            tenant, draft_profile, draft_receipt,
        )
        assert await raw.fetchval(
            "SELECT state FROM public.writing_style_profiles "
            "WHERE tenant_id=$1 AND profile_id=$2",
            tenant, draft_profile,
        ) == "revoked"
        assert await raw.fetchval(
            "SELECT revoked_at IS NOT NULL "
            "FROM public.writing_style_document_consents "
            "WHERE tenant_id=$1 AND receipt_id=$2",
            tenant, draft_receipt,
        ) is True
        # The sample metadata may still contain old style_use_allowed=true:
        # its authority was revoked by the profile lifecycle, not by a
        # mutable or browser-owned evidence Boolean.
        assert await raw.fetchval(
            "SELECT style_use_allowed FROM public.writing_style_sample_evidence "
            "WHERE tenant_id=$1 AND profile_id=$2 AND sample_id=$3",
            tenant, draft_profile, draft_sample,
        ) is True
        await raw.execute(
            "INSERT INTO public.writing_style_revisions "
            "(tenant_id,profile_id,revision_id,revision_number,"
            "approved_expression,content_digest,approved_by) "
            "VALUES ($1,$2,$3,1,'{}'::jsonb,$4,$5)",
            tenant, draft_profile, draft_revision, "d" * 64, owner,
        )
        with pytest.raises(asyncpg.PostgresError):
            await scoped(
                owner, tenant,
                "UPDATE public.writing_style_profiles "
                "SET state='published',publication_revision=1,current_revision_id=$1 "
                "WHERE tenant_id=$2 AND profile_id=$3",
                draft_revision, tenant, draft_profile,
            )
        with pytest.raises(asyncpg.PostgresError):
            await scoped(
                owner, tenant,
                "INSERT INTO public.writing_style_grants "
                "(tenant_id,profile_id,owner_actor_id,actor_id,purpose,granted_by) "
                "VALUES ($1,$2,$3,$4,'draft_email',$3)",
                tenant, draft_profile, owner, other_actor,
            )

    finally:
        if engine is not None:
            await engine.dispose()
        await raw.close()
