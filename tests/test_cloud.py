from popelka import cloud


def test_region_hosts():
    assert cloud.Account(region="eu").host == "openapi.tuyaeu.com"
    assert cloud.Account(region="us").host == "openapi.tuyaus.com"


def test_signature_is_stable_hex():
    account = cloud.Account(username="u", password="p", client_id="abc", client_secret="s3cret")
    headers = account._sign({"grant_type": "1"}, {"username": "dXNlcg=="})
    assert headers["sign_method"] == "HMAC-SHA256"
    assert len(headers["sign"]) == 64
    assert headers["sign"] == headers["sign"].upper()
    assert headers["client_id"] == "abc"


def test_country_code_default():
    assert cloud.Account(region="eu").country_code == "84"


def test_load_account_env():
    account = cloud.load_account(
        {"TUYA_USER": "a@b.c", "TUYA_PASS": "hunter2", "TUYA_REGION": "us"}
    )
    assert account.username == "a@b.c"
    assert account.password == "hunter2"
    assert account.host == "openapi.tuyaus.com"
