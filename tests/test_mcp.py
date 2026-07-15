"""
MCP tool-surface tests: schema shape, title/URL handling, and error mapping.
"""

import io
import json
from pathlib import Path

import pytest

from conftest import GRUB_REVID, MISSING_PAGE, declared_version
from arch_wiki_mcp import extractor, tools, protocol, server

CONTENT_TOOLS = {"search", "page", "sections", "section", "commands", "warnings", "links"}


def test_extract_title_from_url():
    assert tools.extract_title_from_url("GRUB") == "GRUB"
    assert tools.extract_title_from_url("https://wiki.archlinux.org/title/GRUB") == "GRUB"
    assert (
        tools.extract_title_from_url("https://wiki.archlinux.org/title/GRUB#Installation")
        == "GRUB"
    )


def test_extract_title_from_url_rejects_unparseable():
    with pytest.raises(ValueError):
        tools.extract_title_from_url("https://wiki.archlinux.org/")


def test_tools_list_surface_is_exact():
    """examples() was removed; it violated the Exclusive Command Source rule."""
    listed = {t["name"] for t in protocol._handle_tools_list(1)["result"]["tools"]}
    assert listed == CONTENT_TOOLS
    assert "examples" not in listed

    # A tool advertised but not routable answers every call with "Unknown tool";
    # one routable but unadvertised is reachable by a client that guesses. Only
    # the schema was pinned, so nothing held the two in step.
    assert set(tools._TOOL_DISPATCH) == CONTENT_TOOLS


def test_usage_prompt_does_not_bless_heuristic_inference():
    prompt = protocol._handle_prompts_get(1, {"name": "arch-wiki-usage"})
    text = prompt["result"]["messages"][0]["content"]["text"]
    assert "examples()" not in text
    assert "Heuristic inference" not in text
    assert "must not synthesize" in text


def test_page_tool():
    result = tools.tool_page("GRUB")
    assert result["title"] == "GRUB"
    assert result["revid"] == GRUB_REVID
    assert result["url"] == "https://wiki.archlinux.org/title/GRUB"
    assert len(result["sections"]) == 73


def test_page_tool_accepts_url():
    assert tools.tool_page("https://wiki.archlinux.org/title/GRUB")["title"] == "GRUB"


def test_sections_tool():
    sections = tools.tool_sections("GRUB")["sections"]
    assert len(sections) == 73
    assert sections[0]["anchor"]
    assert "byteoffset" in sections[0]


def test_section_tool_provenance():
    result = tools.tool_section("GRUB", "Installation")
    for field in (
        "title",
        "url",
        "revid",
        "section_anchor",
        "section_heading",
        "extraction_method",
        "content",
        "content_hash",
    ):
        assert result[field] is not None, f"{field} must carry provenance"
    assert result["url"] == "https://wiki.archlinux.org/title/GRUB#Installation"


def test_commands_tool_schema():
    blocks = tools.tool_commands("GRUB", "Installation")["commands"]
    assert blocks, "GRUB#Installation contains code blocks"
    for block in blocks:
        for field in (
            "content",
            "content_raw",
            "content_hash",
            "block_type",
            "source_pattern",
            "language",
            "header",
            "placeholders",
            "source_url",
            "revid",
        ):
            assert field in block


def test_commands_tool_full_page():
    blocks = tools.tool_commands("GRUB")["commands"]
    assert len(blocks) == 60  # 17 bc + 8 hc + 35 indented


def test_warnings_tool():
    found = tools.tool_warnings("GRUB", "Installation")["warnings"]
    for warning in found:
        assert warning["source_url"].endswith("#Installation")
        assert warning["content_hash"]


def test_links_tool():
    found = tools.tool_links("GRUB", "Installation")["links"]
    for link in found:
        assert link["source_page"] == "GRUB"
        assert not link["target_page"].startswith(("Category:", "File:"))


def test_missing_anchor_raises_rather_than_returning_a_silent_empty_list():
    """
    The dispatch layer must surface a failure, not a silent [].

    This asserted `"error" in result` when handle_tool_call() returned failures
    as dicts. That shape is what let the transport ship them as successes, so
    the failure is now raised and a caller has to handle it.
    """
    with pytest.raises(extractor.SectionNotFoundError):
        tools.handle_tool_call("commands", {"title_or_url": "GRUB", "anchor": "Bogus"})


def test_missing_page_raises():
    with pytest.raises(extractor.PageNotFoundError):
        tools.handle_tool_call("page", {"title_or_url": MISSING_PAGE})


def test_removed_examples_tool_is_rejected():
    """examples() violated the Exclusive Command Source rule and must stay gone."""
    with pytest.raises(tools.UnknownToolError):
        tools.handle_tool_call("examples", {"title_or_url": "GRUB"})


def test_an_unknown_tool_is_a_protocol_error_not_a_tool_error(monkeypatch, capsys):
    """
    Nothing ran, so there is nothing for a model to see and self-correct from.
    An unknown tool must not arrive as an isError result alongside tools that
    did run -- MCP reserves protocol errors for a fault in the request itself.
    """
    response = _call_tool("examples", {"title_or_url": "GRUB"}, monkeypatch, capsys)

    assert "result" not in response
    assert response["error"]["code"] == -32602


def test_search_tool():
    results = tools.tool_search("GRUB")["results"]
    assert results
    assert results[0]["title"]
    assert results[0]["url"].startswith("https://wiki.archlinux.org/title/")


def test_search_puts_the_exact_title_first():
    """
    Full-text search alone buries it: searching GRUB returned GRUB2 (Indonesia)
    before GRUB. The wiki's own search box answers the exact-title question too.
    """
    results = tools.tool_search("GRUB")["results"]
    assert results[0]["title"] == "GRUB"
    assert results[0]["match"] == "title"
    assert all(r["match"] == "text" for r in results[1:])


def test_search_answers_a_multiword_question():
    """
    srwhat has no default on this wiki, so the API searched TITLES ONLY and
    search("wifi not working") returned [] while the wiki held 47 matching
    pages. [] is this MCP's way of saying the wiki specifies nothing, so the
    discovery entry point was manufacturing silence.
    """
    results = tools.tool_search("wifi not working")["results"]
    assert results, "the wiki has dozens of matching pages"
    assert all(r["match"] == "text" for r in results)


def test_search_asks_the_wiki_both_questions(monkeypatch):
    """
    Asserts the REQUEST, because the response cannot tell us.

    The offline fixture is keyed by srsearch and ignores srwhat, so it hands back
    the same JSON whichever mode we ask for. I reverted search() to title-only and
    the test above stayed green. The bug lives in the query; only the outgoing
    params show it -- exactly as with the redirect-revid lookup.
    """
    sent = []
    original = extractor._fetch

    def _spy(params, timeout=30, key=None):
        sent.append(params)
        return original(params, timeout, key)

    monkeypatch.setattr(extractor, "_fetch", _spy)
    tools.tool_search("GRUB")

    modes = [p.get("srwhat") for p in sent if p.get("list") == "search"]
    assert modes == ["nearmatch", "text"], f"srwhat sequence was {modes}"
    assert "title" not in modes, "title-only search is what returned [] for real questions"


def test_search_tool_zero_results():
    """The only honest empty result: the wiki really has nothing."""
    assert tools.tool_search("zzzqqxnotathing")["results"] == []


def _drive_server(stdin_text, monkeypatch, capsys):
    """Feed raw lines to the stdio loop; return the parsed responses."""
    monkeypatch.setattr(protocol.sys, "stdin", io.StringIO(stdin_text))
    protocol.run_mcp_server()
    return [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]


def _call_tool(name, arguments, monkeypatch, capsys):
    """Drive one tools/call over the real stdio transport; return the response."""
    request = {
        "jsonrpc": "2.0",
        "id": 9,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }
    return _drive_server(json.dumps(request) + "\n", monkeypatch, capsys)[0]


def test_a_parse_error_never_answers_with_a_previous_request_id(monkeypatch, capsys):
    """
    A malformed line must not be blamed on the last request that parsed.

    msg_id used to survive the iteration that bound it, so an unparseable line
    emitted an error carrying the id of an already-answered request -- a client
    keyed on id sees its result overwritten. JSON-RPC 2.0: null when unknown.
    """
    responses = _drive_server(
        '{"jsonrpc":"2.0","id":1,"method":"tools/list"}\nNOT JSON\n', monkeypatch, capsys
    )

    assert len(responses) == 2
    assert responses[0]["id"] == 1 and "result" in responses[0]
    assert responses[1]["id"] is None, "parse error stole the id of request 1"


def test_unparseable_input_is_a_parse_error_not_an_internal_one(monkeypatch, capsys):
    """
    JSON-RPC 2.0 reserves -32700 for input it cannot parse and -32603 for a fault
    inside the server. The loop's catch-all answered a client's malformed line
    with -32603, so the server confessed to a bug that belonged to the request --
    the same conflation isError and -32602 were introduced to end, one layer down.
    """
    responses = _drive_server("NOT JSON\n", monkeypatch, capsys)

    assert responses[0]["error"]["code"] == -32700


def test_a_genuine_server_fault_is_still_an_internal_error(monkeypatch, capsys):
    """The converse: -32700 must not swallow faults that really are ours."""
    def _explode(msg_id):
        raise RuntimeError("boom")

    monkeypatch.setattr(protocol, "_handle_tools_list", _explode)
    responses = _drive_server('{"jsonrpc":"2.0","id":3,"method":"tools/list"}\n', monkeypatch, capsys)

    assert responses[0]["error"]["code"] == -32603


def _descendants(cls):
    """Every subclass, however deep -- a new one must not slip past the pin."""
    for sub in cls.__subclasses__():
        yield sub
        yield from _descendants(sub)


def test_the_documented_subset_is_the_implemented_one(monkeypatch, capsys):
    """
    MCP_PROTOCOL.md states exactly which methods, capabilities and error codes
    this server supports, so that a deviation is a decision rather than an
    accident. A document nothing checks is a claim, not a contract: pin it to the
    implementation, so a method added or dropped in code fails here until the
    document says so too.
    """
    doc = (Path(__file__).parent.parent / "MCP_PROTOCOL.md").read_text()

    for method in protocol._METHOD_DISPATCH:
        assert f"`{method}`" in doc, f"{method} is routed but undocumented"

    for code in ("-32700", "-32601", "-32602", "-32603"):
        assert code in doc, f"error code {code} is emitted but undocumented"

    # The isError codes are the table the document calls the one it cares about
    # most, and they were the one thing nothing pinned: a new ArchWikiError
    # subclass would have reached an agent under a category no document defined.
    for failure in _descendants(extractor.ArchWikiError):
        assert f"`{failure.code}`" in doc, f"{failure.code} can reach an agent but is undocumented"

    responses = _drive_server(
        '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}\n', monkeypatch, capsys
    )
    result = responses[0]["result"]

    assert f"`{result['protocolVersion']}`" in doc, "the advertised protocol version is undocumented"
    for capability in result["capabilities"]:
        assert f"`{capability}`" in doc, f"capability {capability} is advertised but undocumented"


def test_every_routed_method_is_declared(monkeypatch, capsys):
    """The dispatch table is what the document is checked against; it must be true."""
    for method in protocol._METHOD_DISPATCH:
        responses = _drive_server(
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": {}}) + "\n",
            monkeypatch,
            capsys,
        )
        error = responses[0].get("error", {})
        assert error.get("code") != -32601, f"{method} is declared supported but not routed"

    unrouted = _drive_server(
        '{"jsonrpc":"2.0","id":1,"method":"resources/list"}\n', monkeypatch, capsys
    )
    assert unrouted[0]["error"]["code"] == -32601, "an unsupported method must say so"


def test_server_info_version_matches_the_package_version(monkeypatch, capsys):
    """
    The only way a client can tell a reloaded server from a stale process is
    serverInfo.version. Nothing pinned it to pyproject, so it could silently
    lag a release and quietly answer for the previous build.
    """
    declared = declared_version()

    responses = _drive_server(
        '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}\n', monkeypatch, capsys
    )
    assert responses[0]["result"]["serverInfo"]["version"] == declared


def test_tools_call_without_a_name_is_invalid_params(monkeypatch, capsys):
    responses = _drive_server(
        '{"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"arguments":{}}}\n',
        monkeypatch,
        capsys,
    )

    assert responses[0]["id"] == 7
    assert responses[0]["error"]["code"] == -32602


def test_a_failed_extraction_is_not_dressed_up_as_a_successful_call(monkeypatch, capsys):
    """
    test_failures.py makes the extractor fail closed on a missing page. The MCP
    layer then re-opened it: handle_tool_call() turned the ValueError into a
    plain {"error": ...} dict, and _handle_tools_call() shipped that dict inside
    a *successful* result.content. An agent reading result.content sees text and
    has no protocol-level signal it is holding an error, so the wiki's silence
    becomes an answer. isError is that signal.
    """
    response = _call_tool("page", {"title_or_url": MISSING_PAGE}, monkeypatch, capsys)

    assert "result" in response, "extraction failure is a tool error, not a protocol error"
    assert response["result"]["isError"] is True, "a failed page lookup read as success"


def test_a_failed_extraction_carries_a_machine_readable_category(monkeypatch, capsys):
    """A caller must be able to tell a missing page from an upstream outage."""
    response = _call_tool("page", {"title_or_url": MISSING_PAGE}, monkeypatch, capsys)

    payload = json.loads(response["result"]["content"][0]["text"])
    assert payload["code"] == "page_not_found"
    assert payload["error"], "the human-readable message is still required"


def test_a_missing_anchor_is_distinguishable_from_a_missing_page(monkeypatch, capsys):
    response = _call_tool(
        "section", {"title_or_url": "GRUB", "anchor": "Bogus_anchor"}, monkeypatch, capsys
    )

    payload = json.loads(response["result"]["content"][0]["text"])
    assert payload["code"] == "section_not_found"


def test_a_successful_call_is_not_flagged_as_an_error(monkeypatch, capsys):
    """The converse guard: isError must not fire on the happy path."""
    response = _call_tool("page", {"title_or_url": "GRUB"}, monkeypatch, capsys)

    assert response["result"].get("isError", False) is False


# --- Argument validation (issue #20) ---------------------------------------
#
# The dispatch table indexed arguments["query"] and arguments["title_or_url"]
# straight, so a client that omitted one got a KeyError -- reported to the agent
# as `internal_error`, i.e. "this server has a bug", when in fact its own call
# was malformed. Nothing ran, so it is a fault in the request: -32602, the same
# class as an unknown tool.

MALFORMED_CALLS = [
    pytest.param("search", {}, id="search-without-query"),
    pytest.param("page", {}, id="page-without-title"),
    pytest.param("sections", {}, id="sections-without-title"),
    pytest.param("section", {"title_or_url": "GRUB"}, id="section-without-anchor"),
    pytest.param("commands", {}, id="commands-without-title"),
    pytest.param("warnings", {}, id="warnings-without-title"),
    pytest.param("links", {}, id="links-without-title"),
    pytest.param("page", {"title_or_url": 7}, id="title-not-a-string"),
    pytest.param("page", {"title_or_url": ""}, id="title-empty"),
    pytest.param("page", {"title_or_url": "   "}, id="title-blank"),
    pytest.param("search", {"query": ""}, id="query-empty"),
    pytest.param("section", {"title_or_url": "GRUB", "anchor": ""}, id="anchor-empty"),
    pytest.param("search", {"query": "grub", "limit": "10"}, id="limit-a-string"),
    pytest.param("search", {"query": "grub", "limit": 1.5}, id="limit-fractional"),
    pytest.param("search", {"query": "grub", "limit": 0}, id="limit-below-minimum"),
    pytest.param("search", {"query": "grub", "limit": 51}, id="limit-above-maximum"),
    # bool is an int subclass in Python, so True would otherwise sail through an
    # isinstance(x, int) check and reach the wiki as srlimit=1.
    pytest.param("search", {"query": "grub", "limit": True}, id="limit-a-bool"),
]


@pytest.mark.parametrize("tool,arguments", MALFORMED_CALLS)
def test_a_malformed_call_is_invalid_params_over_the_wire(tool, arguments, monkeypatch, capsys):
    """Nothing ran, so there is no tool result to carry an isError."""
    response = _call_tool(tool, arguments, monkeypatch, capsys)

    assert "result" not in response, f"{tool}{arguments} produced a tool result"
    assert response["error"]["code"] == -32602


@pytest.mark.parametrize("tool,arguments", MALFORMED_CALLS)
def test_a_malformed_call_is_rejected_before_the_extractor_runs(tool, arguments, monkeypatch):
    """The wiki must never be asked a question we already know is malformed."""
    def _no_fetch(*args, **kwargs):
        raise AssertionError("extractor reached with malformed arguments")

    monkeypatch.setattr(extractor, "_fetch", _no_fetch)

    with pytest.raises(tools.InvalidParamsError):
        tools.handle_tool_call(tool, arguments)


def test_a_blank_string_is_refused_by_a_rule_the_schema_declares():
    """
    The validator rejected "   " by checking minLength against value.strip(). But a
    one-space string *satisfies* minLength: 1, so this enforced a rule the schema
    never stated -- the same lie #20 exists to end, told in the strict direction.
    Refusing a blank title is right; the schema has to say so.
    """
    advertised = {t["name"]: t for t in protocol._handle_tools_list(1)["result"]["tools"]}
    title = advertised["page"]["inputSchema"]["properties"]["title_or_url"]

    assert title.get("pattern"), "blank-rejection is enforced but nowhere declared"

    with pytest.raises(tools.InvalidParamsError):
        tools.handle_tool_call("page", {"title_or_url": "   "})


def test_an_explicit_null_id_still_gets_an_answer(monkeypatch, capsys):
    """
    A notification is a message with NO id member. `"id": null` is a request that
    happens to carry a null id, and JSON-RPC says answer it (with a null id).
    Checking `msg_id is None` conflated the two, so a client sending an explicit
    null id was met with silence and waited forever for a reply that never came.
    """
    responses = _drive_server(
        '{"jsonrpc":"2.0","id":null,"method":"tools/list"}\n', monkeypatch, capsys
    )

    assert responses, "an explicit null id was silently swallowed as a notification"
    assert responses[0]["id"] is None
    assert "result" in responses[0]


def test_a_notification_is_still_answered_with_silence(monkeypatch, capsys):
    """The converse: no id member at all expects no reply, and must not get one."""
    responses = _drive_server(
        '{"jsonrpc":"2.0","method":"notifications/initialized"}\n', monkeypatch, capsys
    )

    assert responses == []


@pytest.mark.parametrize("params", ["[]", '"nope"', "42"])
def test_non_object_params_are_invalid_params_not_our_bug(params, monkeypatch, capsys):
    """
    `params` is an object by construction. A list reached params.get(), raised
    AttributeError into the catch-all, and answered -32603 Internal error -- the
    server confessing to a bug that belongs to the request.
    """
    responses = _drive_server(
        '{"jsonrpc":"2.0","id":5,"method":"tools/call","params":%s}\n' % params,
        monkeypatch,
        capsys,
    )

    assert responses[0]["error"]["code"] == -32602


def test_a_non_object_request_is_an_invalid_request_not_our_bug(monkeypatch, capsys):
    """
    `42` and `[]` are valid JSON. message.get() then raised AttributeError and the
    catch-all answered -32603 Internal error -- the server confessing to a bug that
    belongs to the request. JSON-RPC 2.0 reserves -32600 for exactly this.
    """
    responses = _drive_server("42\n[1,2]\n", monkeypatch, capsys)

    assert [r["error"]["code"] for r in responses] == [-32600, -32600]


def test_too_many_cli_arguments_are_refused_rather_than_dropped(monkeypatch, capsys):
    """
    zip() stops at the shorter sequence, so `section GRUB Installation extra`
    silently ignored `extra` and succeeded. A caller mistake that reports success is
    the shape of every bug in this repository.
    """
    code, _, stderr = _run_cli(
        ["section", "GRUB", "Installation", "extra"], monkeypatch, capsys
    )

    assert code == 1
    assert json.loads(stderr)["code"] == "invalid_params"


def test_the_declared_limit_schema_matches_what_is_enforced():
    """
    Declared `number` with no bounds, the schema promised a client that 1e9 --
    or 2.5 -- was acceptable, and the code then passed it to the wiki. A schema
    the runtime does not honour is a lie told to every client that reads it.
    """
    advertised = {t["name"]: t for t in protocol._handle_tools_list(1)["result"]["tools"]}
    limit = advertised["search"]["inputSchema"]["properties"]["limit"]

    assert limit["type"] == "integer"
    assert limit["minimum"] == 1
    assert limit["maximum"] == tools.SEARCH_LIMIT_MAX
    assert limit["default"] == tools.SEARCH_LIMIT_DEFAULT


@pytest.mark.parametrize("limit", [1, 10, 50])
def test_a_limit_within_bounds_is_accepted(limit):
    """The converse guard: validation must not reject what the schema allows."""
    assert tools.handle_tool_call("search", {"query": "GRUB", "limit": limit})["results"]


def _run_cli(argv, monkeypatch, capsys):
    """Drive main() as a shell would; return (exit_code, stdout, stderr)."""
    monkeypatch.setattr(protocol.sys, "argv", ["server.py"] + argv)
    with pytest.raises(SystemExit) as exit_info:
        server.main()
    captured = capsys.readouterr()
    return exit_info.value.code, captured.out, captured.err


@pytest.mark.parametrize("argv", [
    pytest.param(["page"], id="page-without-title"),
    pytest.param(["section", "GRUB"], id="section-without-anchor"),
    pytest.param(["search", "grub", "notanint"], id="limit-not-an-int"),
    pytest.param(["search", "grub", "999"], id="limit-above-maximum"),
    pytest.param(["page", MISSING_PAGE], id="missing-page"),
])
def test_the_cli_fails_closed_with_a_coded_error(argv, monkeypatch, capsys):
    """
    The argv build sat outside main()'s try, so a missing argument answered the
    shell with a raw traceback while the same mistake over MCP got a clean coded
    error -- and nothing tested the CLI, which is how it survived. A caller that
    checks only $? must still be able to tell the call failed.
    """
    code, stdout, stderr = _run_cli(argv, monkeypatch, capsys)

    assert code == 1, "a failed call exited 0; the shell would believe it worked"
    assert stdout == "", "a failure must not be written to stdout as if it were a result"
    assert json.loads(stderr)["code"], "stderr must carry a machine-readable category"


def test_the_cli_reports_an_unknown_tool_with_usage(monkeypatch, capsys):
    code, _, stderr = _run_cli(["bogustool"], monkeypatch, capsys)

    assert code == 1
    assert "Unknown tool: bogustool" in stderr
    # The usage text is generated from the schema, so every routable tool appears.
    for tool in tools._TOOL_DISPATCH:
        assert tool in stderr


def test_the_cli_prints_a_result_on_the_happy_path(monkeypatch, capsys):
    """The converse guard: a good call must still exit 0 with JSON on stdout."""
    monkeypatch.setattr(protocol.sys, "argv", ["server.py", "page", "GRUB"])
    server.main()

    assert json.loads(capsys.readouterr().out)["title"] == "GRUB"


def test_an_omitted_limit_defaults_to_the_declared_value(monkeypatch):
    """
    Asserting only that results came back would pass whether the applied default
    were 10, 50, or a stale fallback in the dispatch lambda. Assert the number
    that actually reached the extractor.
    """
    seen = []
    original = extractor.search
    monkeypatch.setattr(
        extractor, "search", lambda q, limit=None: seen.append(limit) or original(q, limit)
    )

    tools.handle_tool_call("search", {"query": "GRUB"})

    assert seen == [tools.SEARCH_LIMIT_DEFAULT]
