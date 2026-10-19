from uuid import UUID

import pytest
from fastapi import HTTPException
from finorch_api.config import Settings
from finorch_api.security.demo_identity import DEMO_USER_ONE_ID, get_current_demo_actor


@pytest.mark.parametrize("environment", ["development", "test"])
def test_demo_identity_uses_server_selected_user(environment: str) -> None:
    selected_user = UUID("00000000-0000-4000-8000-000000000002")

    actor = get_current_demo_actor(Settings(environment=environment, demo_user_id=selected_user))

    assert actor.user_id == selected_user


def test_demo_identity_is_disabled_in_production() -> None:
    with pytest.raises(HTTPException) as error:
        get_current_demo_actor(Settings(environment="production"))

    assert error.value.status_code == 503
    assert error.value.detail == "Demo identity is unavailable."


def test_default_demo_identity_is_a_synthetic_user() -> None:
    assert Settings().demo_user_id == DEMO_USER_ONE_ID
