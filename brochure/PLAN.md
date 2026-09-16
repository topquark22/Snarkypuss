# Snarkypuss Brochure Plan

## Format and audience

- **Format:** A5 portrait (148 × 210 mm), full colour.
- **Length:** 16 pages, suitable for saddle-stitch booklet printing.
- **Audience:** Non-technical readers who already understand what a VPN is and have some awareness of Canadian online-privacy issues.
- **Tone:** Informational and non-partisan. Explain the relevant legislation, the government's stated rationale, privacy concerns, and VPN-provider responses without telling readers what political conclusion to draw.
- **Visual identity:** Use the Snarkypuss character reference consistently throughout the brochure. Major concepts should be explained visually wherever practical.
- **Publication dating:** Treat discussion of legislation, government policy, and VPN-provider positions as a dated snapshot rather than timeless information. The initial brochure edition is **September 2026**, and legal/policy content should be researched and described as current as of that date.

## Project positioning

The brochure must make these points clear:

- Snarkypuss is **open-source software**.
- Snarkypuss is **not a commercial product or VPN service**.
- There is no centralized Snarkypuss network or subscription service.
- Each user privately hosts their own installation on a VPS they control and separately chooses and contracts with their own commercial VPN provider.
- Snarkypuss is **not intended to break, evade, or circumvent applicable law**.
- Snarkypuss does not claim to provide anonymity, alter anyone's legal obligations, defeat lawful process, or control the policies or conduct of a commercial VPN provider.

## Page plan

Page 1 is a right-hand page, so in the stapled booklet the facing pairs are
2–3, 4–5, 6–7, 8–9, 10–11, 12–13 and 14–15. The three major visual spreads
must therefore begin on an even page; a spread starting on an odd page would
be split by a page turn. The build enforces this.

### Page 1 — Cover

**Snarkypuss: A Private Bridge to Your VPN**

Strong Snarkypuss character artwork, subtitle, and minimal text. Establish a polished but slightly playful visual identity while treating the privacy subject seriously.

### Page 2 — Why Snarkypuss? / A Changing Privacy Landscape

Introduce the premise: Canadians commonly use commercial VPNs for online privacy, while changes in Canada's legislative environment have raised questions about how some VPN providers may operate in Canada in the future.

Begin **A Changing Privacy Landscape** in the lower part of the page, with the dating line

**Legislative context current as of September 2026**

and the opening description of Bill C-8. This date establishes the cutoff for the legal and policy discussion on pages 2–4. Bill status, government descriptions, privacy concerns and provider positions must be researched against that date and supported by the source record in `references/sources.md`.

### Page 3 — Bills C-8 and C-22

Finish Bill C-8 and give greater emphasis to Bill C-22 and lawful access.

Cover:

- what each bill proposes insofar as it is relevant to the brochure;
- the Government of Canada's stated rationale;
- what "lawful access" means in ordinary language;
- relevant safeguards in the legislation; and
- privacy and civil-liberties concerns raised by appropriate authorities and other documented sources.

The treatment must remain factual and non-partisan. Where government and critics characterize a safeguard differently, both must be attributed rather than either being stated as settled fact.

### Page 4 — Why VPN Providers Care

Close the legislative discussion with the Privacy Commissioner's position on Bill C-22 and the amendments subsequently adopted.

Then explain the potential tension between technical-access requirements and commercial VPN services built around encryption and no-logging designs, and present the documented positions of **NordVPN** and **Windscribe**, including statements concerning their continued Canadian operations. Attribute these positions directly rather than characterizing motives.

### Page 5 — What Snarkypuss Is

A full page introducing the project, ending in a compact list:

- privately hosted;
- open source;
- non-commercial;
- operated on the user's own VPS;
- used with the user's separately chosen VPN provider; and
- intended for lawful use.

This page is also a natural home for character artwork, and is currently light.

### Pages 6–7 — The Basic Idea

The first major illustrated spread and the principal explanation of Snarkypuss.

Show:

**Your PC → private WireGuard tunnel → Your VPS → your VPN provider → Internet**

The compact diagram label is simply **Your VPS**.

In accompanying prose, define it as: **Your VPS (Virtual Private Server) is a small-footprint hosted virtual server. It provides the Internet-connected Linux environment Snarkypuss needs without requiring dedicated hardware. A suitable VPS costs approximately US$5 per month.**

Make clear that the commercial VPN software runs on the VPS rather than directly on the Canadian PC and that there is no central Snarkypuss service carrying users' traffic.

Use very little prose; the diagram carries the explanation, and is not restated as a line of text.

### Page 8 — Why Keep the Commercial VPN? / Meet Snarkypuss

Explain why the VPS is not simply used as the final Internet exit. A commercial VPN can provide shared exit infrastructure, many geographic destinations, provider-operated servers, and convenient destination changes.

The VPS acts primarily as the privately controlled bridge to that service.

Begin **Meet Snarkypuss** in the lower portion: introduce the dashboard and the normal user experience.

### Page 9 — Meet Snarkypuss / Choosing Where You Connect

Show what ordinary operation feels like:

- activate the private WireGuard tunnel;
- open the private SnarkyCtl dashboard;
- choose a VPN destination;
- connect; and
- see whether the connection is protected and what public exit is being used.

Explain destination choices in ordinary language, including **Fastest available server**, country, city, server group, and specific-server targets where appropriate.

Explain live provider discovery simply: Snarkypuss can ask the installed VPN provider what choices are currently available instead of relying on an obsolete hard-coded server list.

### Pages 10–11 — Privacy Includes Failure

The second major illustrated spread and the centre of the safety story.

Explain that establishing a VPN connection is only half the problem: Snarkypuss must also behave safely when the provider disconnects, a component fails, or the system cannot establish its state reliably.

Introduce the four effective states visually:

- **Protected VPN** — normal protected Internet use through the commercial VPN.
- **Locked** — safe disconnected state; public Internet forwarding is blocked.
- **Direct VPS** — deliberate exceptional mode in which traffic may leave through the VPS public address without the upstream commercial VPN.
- **Unknown** — Snarkypuss cannot verify the effective path and therefore does not claim that traffic is protected.

Emphasize the fail-closed principle: provider failure must not silently become an unprotected direct connection.

### Pages 12–13 — Under the Hood

The third major visual spread. It explains the internal architecture while preserving a clear distinction between the **SnarkyCtl control plane** and the **network gateway/data plane**.

The spread should be understandable to a curious non-technical reader without requiring knowledge of Linux or web frameworks. The architecture graphic is the dominant element; prose gives way to it.

#### Page 12 — SnarkyCtl Control

**Browser → WireGuard → SnarkyCtl dashboard → Application Server → SnarkyCtl control logic → Privileged control service → Provider adapter → NordVPN / Other providers**

Also show:

- the **Targets Database** beside SnarkyCtl control logic rather than in the main control path;
- an explicit **privilege boundary** between ordinary application/control processing and the privileged control service; and
- the provider adapter as an extensible interface, with NordVPN as the concrete provider and **Other providers** indicating future extensibility without claiming specific additional provider support.

Explain privilege separation briefly: the web dashboard cannot execute arbitrary administrator commands. It can request only defined and validated Snarkypuss operations from the privileged control component.

#### Page 13 — Network Gateway

**WireGuard → Routing / DNS → Provider VPN → Internet**

Show a small, clearly labelled connection from the SnarkyCtl/provider-control side to the Provider VPN indicating that SnarkyCtl **controls and observes** the provider connection. This must not imply that forwarded Internet traffic passes through the SnarkyCtl web application. The connector leaves page 12 toward the gutter and lands on Provider VPN from the left, so it reads as one line across the spread.

The network path and control path use visibly different line weights. Use only orthogonal horizontal and vertical connectors; do not use diagonal arrows.

Keep implementation names such as FastAPI, Starlette, Pydantic, Uvicorn and SQLite out of the architecture diagram. At this audience level, use functional labels such as **Application Server** and **Targets Database** instead.

A small amount of accompanying prose may explain that the reference deployment runs on Linux on a privately controlled VPS.

### Page 14 — More Than `nordvpn connect`

Address the apparent paradox that the basic requirements sound simple while the finished software is substantial.

Contrast the happy path—establish WireGuard and issue a provider connect command—with real-world concerns such as provider failure; routing and forwarding; DNS; firewall and leak-protection state; validation; changing or stale destinations; reboot and service state; installation and upgrades; and recovery from networking mistakes.

The point is that making a connection is easy; making it safe, repeatable, observable and recoverable is the larger engineering problem.

### Page 15 — Boundaries and the Snarkypuss Project

Establish reasonable expectations and project boundaries. Snarkypuss controls a network route to a VPN provider and attempts to make the effective safety state explicit. It does **not**:

- guarantee anonymity;
- prevent websites or services from identifying users by other means;
- change anyone's obligations under applicable law;
- defeat lawful legal process;
- exempt a VPN provider from its own legal obligations; or
- control the policies or conduct of the commercial VPN provider.

Then give project information: open-source and non-commercial status; current release; supported/tested VPN providers; GitHub repository; and a brief note that the architecture is deliberately provider-independent. Make clear again that there is no Snarkypuss company, VPN service, central network or subscription.

Include a conventional publication line such as:

**Brochure edition: September 2026**

This identifies the edition separately from the legal-context cutoff shown on page 2.

### Page 16 — Back cover

Full-page Snarkypuss character artwork echoing the front cover. Include only a short closing line and project URL/QR code. Do not introduce new substantive information.

## Narrative structure

The brochure has four movements:

1. **Pages 2–4 — Why?**  
   Canadian legislative context, Bills C-8 and C-22, and documented VPN-provider responses.

2. **Pages 5–9 — What?**  
   What Snarkypuss is, the basic routing idea, why the commercial VPN remains useful, and the ordinary user experience.

3. **Pages 10–14 — Why is it substantial software?**  
   Fail-closed behaviour, the two-page architecture spread separating the SnarkyCtl control plane from the network gateway, and the real-world failure handling that makes the project larger than it first appears.

4. **Pages 15–16 — Boundaries and project information.**  
   What Snarkypuss does not claim to do, lawful-use framing, open-source/non-commercial status, and project information.

## Layout principles

- Do not force every section to begin on a new page; several sections intentionally begin mid-page.
- Preserve pages 6–7, 10–11, and 12–13 as the three major visual spreads.
- Keep body copy readable at A5 size rather than shrinking text to fit a predetermined layout.
- Prefer diagrams, illustrations, callouts, and concise tables to long blocks of prose.
- Use colour consistently to distinguish the private WireGuard path, the commercial VPN path, safe/locked states, and exceptional states.
- In architecture diagrams, clearly distinguish control flow from forwarded Internet traffic.
- Use only orthogonal horizontal and vertical connectors in the architecture spread; avoid diagonal arrows.
- Keep the Snarkypuss character visually consistent with the approved character reference.
- The brochure should remain useful as an on-screen PDF while also being suitable for full-colour booklet printing.
