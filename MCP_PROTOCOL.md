# The Supported MCP Subset

This server speaks a deliberately small part of the Model Context Protocol. This
document says exactly which part, so that everything outside it is a decision we
made rather than a gap we did not notice.

`tests/test_mcp.py` checks this document against the code: a method routed but
not documented here, or a capability advertised but not listed, fails the suite.
A document nothing checks is a claim; this one is a contract.

## The transport decision

We implement JSON-RPC over stdio directly rather than adopting the official
Python MCP SDK.

The SDK is the better default for most servers, and the reasoning below is not a
criticism of it. It did not fit *this* project:

- **The dependency cost is the product.** `mcp` brings 28 transitive packages --
  `pydantic`, `httpx`, `cryptography`, `PyJWT`, and a full `starlette`/`uvicorn`
  HTTP server stack -- into a stdio-only server whose `dependencies` list is
  empty. This project's claim is a small, auditable evidence path between an
  agent and the wiki. A supply chain thirty packages deep is not that, and the
  web-server half of it would never execute.
- **The protocol surface we need is small.** Five methods, two capabilities, no
  resources, no sampling, no subscriptions. The transport is a few hundred lines
  and every one of them is testable from a string of stdin.
- **The extractor stays independent either way.** `src/extractor.py` knows
  nothing about MCP and never will; that is the boundary worth defending, and
  neither choice threatens it.

What we accept in exchange: we own compatibility. The MCP specification will
move, and nothing upstream will tell us. That is why the subset below is written
down and pinned by tests, and why "we do not implement that" is stated rather
than left to be discovered.

Revisit this if the server ever needs resources, sampling, progress
notifications, or an HTTP transport. At that point the SDK is doing real work and
its dependencies are buying something.

## Protocol version

`2024-11-05`, advertised in the `initialize` result.

We do not negotiate. A client requesting a different version still receives
`2024-11-05`, and may decide for itself whether to proceed.

## Capabilities

Advertised in the `initialize` result:

| Capability | Meaning |
| --- | --- |
| `tools` | The seven extraction tools. Their signatures live in [MCP_SETUP.md](MCP_SETUP.md); this document covers only the protocol around them. |
| `prompts` | One prompt, `arch-wiki-usage`. |

Not advertised, and not implemented: `resources`, `sampling`, `roots`,
`completions`, `logging`. A client that assumes them will find them absent from
`initialize`, which is the correct place to find that out.

## Methods

| Method | Supported |
| --- | --- |
| `initialize` | Yes. Returns protocol version, server info, capabilities. |
| `tools/list` | Yes. Returns the tools and their input schemas. |
| `tools/call` | Yes. See *Errors* below for the failure contract. |
| `prompts/list` | Yes. |
| `prompts/get` | Yes. |

Anything else -- `resources/list`, `completion/complete`, `logging/setLevel`,
`sampling/createMessage` -- answers `-32601` (Method not found). That is a
statement, not an oversight.

## Notifications

A JSON-RPC message with no `id` is a notification and receives no reply. The
client's `notifications/initialized` after the handshake is therefore silently
accepted, which is the correct behaviour, not a missing feature.

We send no notifications of our own. There is no progress reporting, no
`notifications/tools/list_changed`: the tool list is fixed at build time and
cannot change while the process runs.

## Errors

The distinction this server cares about most, because its whole purpose is that
an agent can tell evidence from the absence of evidence.

**A tool that ran and failed** is a *successful* JSON-RPC response whose result
carries `isError: true` and a machine-readable `code`. The model sees it and can
self-correct -- ask for a different anchor, retry an outage, supply a plain title
instead of an unparseable URL.

| `code` | Meaning |
| --- | --- |
| `page_not_found` | The wiki has no such page. An answer, not a failure to answer. |
| `section_not_found` | The page exists; the anchor does not. |
| `evidence_unresolvable` | Page and section exist, but the text cannot be quoted with provenance intact (a transcluded section, an offset that did not land on its heading). A refusal, not a miss. |
| `upstream_api_error` | The wiki errored, or did not answer at all. Retryable. |
| `malformed_wiki_url` | A well-formed string that is not a resolvable wiki URL. |
| `internal_error` | A bug in this server. Logged with a traceback. |

**A fault in the request itself** is a JSON-RPC error. Nothing ran, so there is
no tool result and nothing for a model to self-correct from.

| Code | Meaning |
| --- | --- |
| `-32700` | Parse error. The line was not JSON. Answered with a null `id`, since the id could not be read. |
| `-32601` | Method not found. The method is outside the subset above. |
| `-32602` | Invalid params. An unknown tool or prompt, a missing or wrong-typed argument, a value the schema forbids. |
| `-32603` | Internal error. Ours. |

The rule: `-32603` and `internal_error` mean *we* were wrong. Everything else
names something true about the request or about the wiki. A server that reports
a client's malformed line as an internal error is confessing to a bug it does not
have, and an agent cannot act correctly on a lie in either direction.

## Argument validation

Every `tools/call` is validated against the schema `tools/list` advertises for
that tool -- the same declaration, not a second copy of it. A rule the schema
does not state is not enforced, and a rule it states is. `search.limit` is an
integer, 1..50, default 10; strings declare `minLength: 1`; every schema declares
`additionalProperties: false`.

## Shutdown

The server runs until stdin closes, then exits. There is no `shutdown` method and
no `exit` notification; closing the pipe is the whole protocol.

## What is tested

`tests/test_mcp.py` drives the real stdio loop -- a string in, parsed JSON-RPC
out -- rather than calling handlers directly. It covers the handshake, every
routed method, notifications, malformed input, unknown tools, unknown methods,
invalid parameters, tool failures at the protocol level, and the guarantee that a
successful call is never flagged as an error. The subset in this document is
checked against the implementation on every run.
