# Research data access

## Local calculation engine

`GET /api/tokens/{address}/local-research` reads finalized mint state and at most
20 largest token accounts through the configured `SOLANA_RPC_URL`. No trading
or signing methods are used. Mint/freeze and account concentration can be
calculated without a paid analytics API. Pool vaults are NOT excluded. Account
concentration is explicitly NOT wallet/owner concentration. Sample slots are
returned; the two reads are not an atomic snapshot. Wrapped native SOL has no
normal supply denominator and does not get a zero concentration result.

Public RPC services may deny or rate-limit getTokenLargestAccounts. The endpoint
then retains successfully fetched authority data and returns partial status.
For sustained use, configure a Solana RPC with access to the required methods.
Do not expose the credential-bearing RPC URL in responses or frontend code.

Pure calculation functions also implement labelled-group supply share,
unrealized-profit coverage and fresh-wallet activity. These functions are tested
but are NOT wired to a complete history/label indexer yet. They require complete
input populations before returning all-holder percentages. Fresh v1 means first
on-chain activity in the previous seven days, with buys in the previous 24h.
An address's first transaction in a truncated history page is not its creation.
Zero cost, unknown cost, closed positions and break-even are distinct states.
The application does NOT yet locally classify phishing, snipers, insiders,
bundlers or professional traders, nor scan AMM LP mint/vault state. A calibrated
rug probability is not implemented. Dex listing payment is off-chain evidence
and cannot be inferred from Solana transfers alone.

Official RPC documentation:
https://solana.com/docs/rpc/http/getaccountinfo
https://solana.com/docs/rpc/http/gettokenlargestaccounts

Verified against official documentation on 2026-11-04.

## Axiom Trade

The [official documentation index](https://docs.axiom.trade/llms.txt) describes
Pulse, Explore and Trader Scan features, but provides no public data API,
authentication contract or API-key creation procedure. Do not confuse Axiom
Trade with axiom.co (observability) or axiom.ai (automation).

Request authorized **read-only analytics access** using the private ticket flow
in [official support](https://docs.axiom.trade/support). Ask for endpoint/schema
documentation, authentication, rate limits, redistribution rights, historical
holder cost basis and definitions of phishing, professional traders and bundles.
There is no verified key-generation flow to describe yet. Do not provide wallet
keys, seed phrases or login/refresh cookies. No unofficial Axiom SDK is installed.

The Signal deck uses corresponding metrics from existing providers; it is NOT
an Axiom data feed. Axiom's bundle detection differs from other providers.
No calibrated Rug % or holder profit % is inferred from a security score or
24h price movement. Profit requires a cost-basis ledger (buys, sells, transfers,
fees, holder population and synchronized price); this pipeline is not connected.
Phishing and Pro Traders stay unavailable without an authorized classifier.

## Bubblemaps

[Official iframe quickstart](https://docs.bubblemaps.io/iframe/quickstart):
the demo Partner ID works on **localhost / 0.0.0.0**, not production domains.
Open `http://localhost:8000` and choose Bubble map → Load interactive map.
The iframe loads on demand; the external provider handles coverage/errors.
No synthetic graph or connections are substituted for missing data.
Wrapped SOL is explicitly unsupported by the provider's map renderer; its
"Map not available" message is a coverage limitation, not an application error.

For deployment, obtain a Partner ID for your domains from contact@bubblemaps.io
and set `BUBBLEMAPS_PARTNER_ID` in the server environment before restart.
This ID is public and is not an API secret. Analytics platforms may require a
commercial agreement: [pricing](https://docs.bubblemaps.io/iframe/pricing).

For raw graph data, obtain an API key on https://pro.bubblemaps.io and use it
server-side in `X-ApiKey`, per [authentication docs](https://docs.bubblemaps.io/data/api/authentication).
The raw Data API is NOT integrated by this change; the official iframe is.

## GMGN Agent API — verified access path

Official sources: https://docs.gmgn.ai/index/gmgn-agent-api and the linked
https://github.com/GMGNAI/gmgn-skills repository. This is distinct from the
older trading/router API and scraping whitelist. The existing application
adapters must be migrated; adding a key alone does not complete the integration.

1. Generate an Ed25519 pair locally following
   https://docs.gmgn.ai/index/generate-public-key (keep the private key private).
2. Visit https://gmgn.ai/ai and paste the entire PUBLIC key, including PEM markers,
   when creating the Agent API key.
3. Configure only the API key for read-only queries. Do not enable Swap or supply
   the signing private key to this analysis application. Do not commit secrets.
4. Agent API queries require IPv4 according to the official docs.

The documented token reference covers holder counts, top-ten supply share,
creator and team holdings, sniper counts, suspected insider holdings, wallet
tags, fresh-wallet ratios, LP data, mint/freeze renouncement and holder PnL rows.
Fresh-wallet ratio is a holder-count ratio, not fresh-held supply; bundler
transaction volume is not bundled-held supply; top-holder PnL is not all-holder
profit coverage. Rug ratio is a provider score, not a calibrated probability.
Phishing, Pro Traders, Fresh buys window and Fresh holding must have confirmed
definitions and complete data before values can be published under those names.

Photon's trading documentation did not yield a verified public analytics API.
https://docs.padre.gg currently redirects to https://trade.padre.gg rather than
an endpoint reference. Do not use similarly named third-party "API docs" as
evidence of official access.

## DEX profile semantics

The read-only `/api/tokens/{address}/listing` adapter uses the documented
[DEX Screener orders endpoint](https://docs.dexscreener.com/api/reference).
An approved `tokenProfile` order means an approved profile was observed.
Ads and boosts do not count. No approved order does not prove that nothing was
paid; pending, cancelled or unobserved orders are not approved profiles.
Provider failure stays Unknown. No API key is required for this endpoint.
