"""
Arch Wiki MCP Server -- the module a client spawns.

This is the entry point: `arch_wiki_mcp.server:main` is the console script pip
installs, and `python -m arch_wiki_mcp.server` runs it too. The name is load-bearing
-- registration.py and every documented config spell it out -- so it stays put while
the implementation lives in siblings:

  - tools.py     the wiki tools and the schema that validates each call
  - protocol.py  JSON-RPC 2.0 over stdio (the MCP transport)
  - cli.py       argv parsing, the mode flags, and main()
"""

from arch_wiki_mcp.cli import main

if __name__ == "__main__":
    main()
