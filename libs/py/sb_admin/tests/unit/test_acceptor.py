import httpx
import pytest
from structlog.testing import capture_logs


async def test_form_lists_input_fields(client: httpx.AsyncClient) -> None:
    response = await client.get("/admin/acceptors/split")
    assert response.status_code == 200
    assert 'name="total"' in response.text
    assert 'name="parts"' in response.text
    assert "Amount to split" in response.text


async def test_post_computes_and_shows_version(client: httpx.AsyncClient) -> None:
    response = await client.post("/admin/acceptors/split", data={"total": "10.00", "parts": "4"})
    assert response.status_code == 200
    assert "<td>2.50</td>" in response.text
    assert "<th>version</th><td>1</td>" in response.text


@pytest.mark.parametrize(
    "data",
    [{"total": "", "parts": "4"}, {"total": "ten", "parts": "4"}, {"total": "1", "parts": "0"}],
)
async def test_invalid_input_rerenders_form_without_500(
    client: httpx.AsyncClient, data: dict[str, str]
) -> None:
    response = await client.post("/admin/acceptors/split", data=data)
    assert response.status_code == 422
    assert 'name="total"' in response.text


async def test_missing_fields_are_422_not_500(client: httpx.AsyncClient) -> None:
    response = await client.post("/admin/acceptors/split", data={})
    assert response.status_code == 422


async def test_input_rejected_shows_its_message(client: httpx.AsyncClient) -> None:
    response = await client.post("/admin/acceptors/strict", data={"n": "1"})
    assert response.status_code == 422
    assert "policy says no" in response.text


async def test_plain_value_error_is_generic_and_logged(client: httpx.AsyncClient) -> None:
    with capture_logs() as logs:
        response = await client.post("/admin/acceptors/boom", data={"n": "1"})
    assert response.status_code == 422
    assert "acceptor failed" in response.text
    assert "secret internal detail" not in response.text
    [entry] = [e for e in logs if e["log_level"] == "error"]
    assert entry["event"] == "admin.acceptor_failed"
    assert entry["slug"] == "boom"
    assert entry["exc_info"] is True


async def test_division_by_zero_is_generic_and_logged(client: httpx.AsyncClient) -> None:
    with capture_logs() as logs:
        response = await client.post("/admin/acceptors/divide", data={"n": "1"})
    assert response.status_code == 422
    assert "acceptor failed" in response.text
    assert "DivisionByZero" not in response.text
    assert any(e["log_level"] == "error" and e["slug"] == "divide" for e in logs)


async def test_input_rejected_is_not_logged_as_error(client: httpx.AsyncClient) -> None:
    with capture_logs() as logs:
        await client.post("/admin/acceptors/strict", data={"n": "1"})
    assert [e for e in logs if e["log_level"] == "error"] == []


async def test_rich_list_fields_use_getlist(client: httpx.AsyncClient) -> None:
    response = await client.post("/admin/acceptors/rich", data={"prices": ["1", "2"]})
    assert response.status_code == 200
    assert "<th>total</th><td>3</td>" in response.text


async def test_rich_list_accepts_single_comma_separated_value(client: httpx.AsyncClient) -> None:
    response = await client.post("/admin/acceptors/rich", data={"prices": "1, 2.5,"})
    assert response.status_code == 200
    assert "<th>total</th><td>3.5</td>" in response.text


async def test_empty_optional_fields_become_absent_so_defaults_apply(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post(
        "/admin/acceptors/rich",
        data={"prices": "1", "amount": "", "count": "", "note": ""},
    )
    assert response.status_code == 200
    assert "<th>count</th><td>None</td>" in response.text
    assert "<th>note</th><td>dflt</td>" in response.text
    assert "<th>total</th><td>1</td>" in response.text


async def test_optional_fields_still_parse_when_given(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/admin/acceptors/rich",
        data={"prices": "1", "amount": "0.5", "count": "3", "note": "hi"},
    )
    assert response.status_code == 200
    assert "<th>total</th><td>1.5</td>" in response.text
    assert "<th>count</th><td>3</td>" in response.text


@pytest.mark.parametrize("data", [{"prices": " , "}, {"prices": ""}, {}])
async def test_blank_required_list_field_is_missing(
    client: httpx.AsyncClient, data: dict[str, str]
) -> None:
    response = await client.post("/admin/acceptors/rich", data=data)
    assert response.status_code == 422
    assert "prices: Field required" in response.text


async def test_non_string_form_values_are_ignored(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/admin/acceptors/rich",
        data={"prices": "1"},
        files={"note": ("n.txt", b"file body"), "count": ("c.txt", b"5")},
    )
    assert response.status_code == 200
    assert "<th>note</th><td>dflt</td>" in response.text
    assert "<th>count</th><td>None</td>" in response.text


async def test_unknown_form_fields_are_ignored(client: httpx.AsyncClient) -> None:
    response = await client.post("/admin/acceptors/rich", data={"prices": "1", "evil": "x"})
    assert response.status_code == 200


def _assert_escaped(html: str, raw: str, escaped: str) -> None:
    assert raw not in html
    assert escaped in html


async def test_get_escapes_title_description_label_and_help(client: httpx.AsyncClient) -> None:
    html = (await client.get("/admin/acceptors/echo")).text
    _assert_escaped(html, "<b>TITLE</b>", "&lt;b&gt;TITLE&lt;/b&gt;")
    _assert_escaped(html, "<i>DESC</i>", "&lt;i&gt;DESC&lt;/i&gt;")
    _assert_escaped(html, "<u>LABEL</u>", "&lt;u&gt;LABEL&lt;/u&gt;")
    _assert_escaped(html, "<s>HELP</s>", "&lt;s&gt;HELP&lt;/s&gt;")


async def test_result_and_input_value_are_escaped(client: httpx.AsyncClient) -> None:
    html = (await client.post("/admin/acceptors/echo", data={"text": "<em>X</em>"})).text
    assert "<em>X</em>" not in html
    assert "<td>&lt;em&gt;X&lt;/em&gt;</td>" in html
    assert 'value="&lt;em&gt;X&lt;/em&gt;"' in html


async def test_rejection_message_is_escaped(client: httpx.AsyncClient) -> None:
    response = await client.post("/admin/acceptors/echo", data={"text": "reject"})
    assert response.status_code == 422
    _assert_escaped(response.text, "<script>rej()</script>", "&lt;script&gt;rej()&lt;/script&gt;")


async def test_requires_login(anon: httpx.AsyncClient) -> None:
    response = await anon.get("/admin/acceptors/split")
    assert response.status_code in (302, 303, 307)
    assert "/login" in response.headers["location"]


async def test_post_requires_login(anon: httpx.AsyncClient) -> None:
    response = await anon.post("/admin/acceptors/split", data={"total": "1", "parts": "1"})
    assert response.status_code in (302, 303, 307)


@pytest.mark.parametrize(
    ("n", "message"),
    [
        ("1", "amount does not fit &lt;NUMERIC&gt;"),
        ("2", "USD vs EUR"),
        ("3", "plain domain refusal"),
    ],
)
async def test_kernel_domain_errors_show_their_message_and_are_not_logged(
    client: httpx.AsyncClient, n: str, message: str
) -> None:
    with capture_logs() as logs:
        response = await client.post("/admin/acceptors/kernel", data={"n": n})
    assert response.status_code == 422
    assert message in response.text
    assert "acceptor failed" not in response.text
    assert [e for e in logs if e["log_level"] == "error"] == []
