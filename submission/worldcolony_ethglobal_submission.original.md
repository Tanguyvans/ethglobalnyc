# WorldColony — ETHGlobal New York 2026 Submission Fields

Use this file to fill out the ETHGlobal project submission form. Replace any `TODO` items with the final deployed links / exact repo settings before submitting.

---

## Project basics

### Project name

WorldColony

### Category

Data/Analytics

### Emoji

🦀

Alternative options if the form/browser does not like the crab emoji:

- 🐜 — colony / swarm
- 🌎 — world / global markets
- 🐝 — swarm intelligence
- ⚽ — World Cup theme

### Demonstration link

TODO: paste the live demo URL here.

Suggested options:

- https://worldcolony.nyc/
- https://www.worldcolony.nyc/
- TODO: final Vercel deployment URL if the custom domain is not ready

### GitHub repository

Primary repo:

https://github.com/Vainglorious/ethglobalnyc

Repository type:

Monorepo

---

## Short description

Use one of these. The form says max 100 characters.

### Recommended

World Cup prediction market colony powered by real Polymarket trade data.

### More technical

Analytics dashboard for a colony of World Cup prediction-market traders.

### More fun / hackathon-style

A World Cup betting colony that learns from real prediction-market trades.

---

## Full description

WorldColony is a World Cup prediction-market experiment that turns a group of live traders into a visible onchain “colony.” The project follows real betting activity around World Cup outcomes and presents it as a dashboard that judges, users, and participants can explore.

The goal is to make prediction-market activity easier to understand. Instead of only showing raw trades or odds, WorldColony frames the activity as a colony of agents making decisions together: which markets they are trading, how conviction changes over time, and what the group is collectively predicting.

For the hackathon demo, WorldColony connects a public project identity to the live trades wallet using ENS records. The ENS name `worldcolony.eth` resolves to the wallet holding the project’s live Polymarket activity, making it possible for judges to independently verify that the project is tied to real market behavior rather than a purely static mockup.

The user-facing product is a browser-based dashboard for exploring the colony’s trades, markets, and story. It combines a World Cup theme with prediction-market analytics so that people can quickly understand what the colony is betting on and why those trades matter.

---

## How it’s made

WorldColony is built as a web dashboard backed by live prediction-market data and public wallet identity. The frontend is a JavaScript web app deployed through Vercel and connected to the project’s public domain. The GitHub repository is a monorepo containing the application code, configuration, and hackathon-specific project files.

The project uses ENS on Ethereum mainnet to create a public, verifiable identity for the colony. The ENS name `worldcolony.eth` is configured to resolve to the wallet that holds the project’s live Polymarket trades, and text records are used to describe the project, link to the website, and tell the story of the colony.

The analytics layer focuses on making trading activity understandable. We pull and organize prediction-market activity from the project wallet and display it in a way that highlights the colony’s current positions, market exposure, and World Cup thesis. The result is a judge-friendly interface that connects a memorable identity, a real wallet, and a live dashboard.

The hacky part is using ENS not just as a wallet alias, but as a narrative and verification layer. A judge can start from `worldcolony.eth`, resolve the address, inspect the project wallet, and then view the dashboard to see the same colony activity explained visually.

---

## Tech stack fields

Use these as the source of truth for the form. Adjust only if the repository is different.

### Ethereum developer tools

Select:

- Hardhat
- web3.js

Possible additions if used in the repo:

- ethers.js
- viem
- wagmi
- RainbowKit

### Blockchain networks

Select:

- Ethereum
- Polygon

Notes:

- Ethereum mainnet is used for ENS identity: `worldcolony.eth`.
- Polygon is relevant because Polymarket activity settles / is represented on Polygon infrastructure.
- If the form has a specific “Polygon” option, prefer that over “Arc” unless Arc is required by a sponsor track.

### Programming languages

Select:

- JavaScript

Possible additions if used in the repo:

- TypeScript
- Solidity
- HTML
- CSS

### Web frameworks

Select:

- Next.js or React, if available

Do **not** select Angular.js unless the repo actually uses Angular. If the current form has Angular.js selected by accident, remove it and choose the correct framework.

### Databases

Select:

- None, if the project is purely frontend / API-based

Possible additions if actually used:

- MongoDB
- PostgreSQL
- Supabase
- Firebase

Only keep MongoDB if the repo actually uses it.

### Design tools

Select:

- None

Possible additions:

- Figma, if mockups or sticker assets were created there
- Canva, if used for presentation or graphics

### Other specific technologies, libraries, frameworks, or tools

Add any that apply:

- ENS
- Polymarket
- Vercel
- Namecheap DNS
- World Cup data / sports markets
- Wallet analytics
- Prediction markets
- Tailwind CSS
- Recharts
- D3.js
- Etherscan / Polygonscan APIs
- Claude Code
- ChatGPT

---

## AI tools used

ChatGPT was used to brainstorm the project story, polish the ETHGlobal submission copy, generate presentation and sticker concepts, and help organize deployment and ENS setup steps. Claude Code was used to implement and iterate on parts of the application, including boilerplate, frontend changes, and smart-contract / wallet-integration logic. AI tools were used as development assistants, but the final project design, product decisions, deployment, and demo flow were directed by the team.

---

## Project rules / eligibility checklist

Before submitting, confirm:

- [ ] Demo link opens in an incognito browser.
- [ ] GitHub repository is public.
- [ ] The correct repository is selected: `Vainglorious/ethglobalnyc`.
- [ ] Repository is marked as `Monorepo` if it contains the full app.
- [ ] ENS name `worldcolony.eth` resolves correctly on mainnet.
- [ ] ENS address points to the live trades wallet.
- [ ] Polygon / Polymarket wallet activity is visible and verifiable.
- [ ] Short description is under 100 characters.
- [ ] Full description is over 280 characters.
- [ ] “How it’s made” is over 280 characters.
- [ ] Tech stack selections match the actual repo.
- [ ] Remove any accidental selections like Angular.js or MongoDB if they are not actually used.

---

## Final paste-ready version

### Short description

World Cup prediction market colony powered by real Polymarket trade data.

### Description

WorldColony is a World Cup prediction-market experiment that turns a group of live traders into a visible onchain colony. The project follows real betting activity around World Cup outcomes and presents it as a dashboard that judges, users, and participants can explore.

The goal is to make prediction-market activity easier to understand. Instead of only showing raw trades or odds, WorldColony frames the activity as a colony of agents making decisions together: which markets they are trading, how conviction changes over time, and what the group is collectively predicting.

For the hackathon demo, WorldColony connects a public project identity to the live trades wallet using ENS records. The ENS name `worldcolony.eth` resolves to the wallet holding the project’s live Polymarket activity, making it possible for judges to independently verify that the project is tied to real market behavior rather than a purely static mockup.

The user-facing product is a browser-based dashboard for exploring the colony’s trades, markets, and story. It combines a World Cup theme with prediction-market analytics so that people can quickly understand what the colony is betting on and why those trades matter.

### How it’s made

WorldColony is built as a web dashboard backed by live prediction-market data and public wallet identity. The frontend is a JavaScript web app deployed through Vercel and connected to the project’s public domain. The GitHub repository is a monorepo containing the application code, configuration, and hackathon-specific project files.

The project uses ENS on Ethereum mainnet to create a public, verifiable identity for the colony. The ENS name `worldcolony.eth` is configured to resolve to the wallet that holds the project’s live Polymarket trades, and text records are used to describe the project, link to the website, and tell the story of the colony.

The analytics layer focuses on making trading activity understandable. We pull and organize prediction-market activity from the project wallet and display it in a way that highlights the colony’s current positions, market exposure, and World Cup thesis. The result is a judge-friendly interface that connects a memorable identity, a real wallet, and a live dashboard.

The hacky part is using ENS not just as a wallet alias, but as a narrative and verification layer. A judge can start from `worldcolony.eth`, resolve the address, inspect the project wallet, and then view the dashboard to see the same colony activity explained visually.

### AI tools used

ChatGPT was used to brainstorm the project story, polish the ETHGlobal submission copy, generate presentation and sticker concepts, and help organize deployment and ENS setup steps. Claude Code was used to implement and iterate on parts of the application, including boilerplate, frontend changes, and smart-contract / wallet-integration logic. AI tools were used as development assistants, but the final project design, product decisions, deployment, and demo flow were directed by the team.
