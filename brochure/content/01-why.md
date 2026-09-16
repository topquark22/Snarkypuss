<!-- page: 1 layout=cover art=images/cover-bleed.png -->

<!-- page: 2 layout=standard -->

# Why Snarkypuss?

Commercial VPN services give people a convenient way to route Internet traffic through an encrypted connection to a provider-operated server. For many users, that service has become an ordinary part of protecting their privacy online.

But the VPN application does not have to run on the same computer that you use every day. Snarkypuss starts with a different arrangement: your computer connects through a private WireGuard tunnel to **Your VPS**, a small-footprint hosted virtual server that you control. The commercial VPN runs there instead.

That separation matters if the legal or commercial environment in Canada changes. Snarkypuss does not replace the commercial VPN, defeat Canadian law, or make anyone anonymous. It gives you a privately controlled bridge between your own computer and the VPN service you have chosen.

## A Changing Privacy Landscape

<!-- snapshot -->

Canada's rules for communications security and lawful access are changing. Two measures are particularly relevant to the background of this project: Bill C-8 and Bill C-22.

**Bill C-8 — An Act Respecting Cyber Security** received Royal Assent on June 15, 2026. It broadens federal authority over the security of Canada's telecommunications networks and enacts the Critical Cyber Systems Protection Act, which places cybersecurity obligations on designated operators in sectors including telecommunications, banking, energy, transportation, and clearing and settlement.

<!-- page: 3 layout=standard -->

The telecommunications amendments took effect on assent; the operator obligations are being phased in by order of the Governor in Council. The government says these measures are intended to protect essential services from increasingly sophisticated cyber threats.

Privacy Commissioner Philippe Dufresne supported the bill's cybersecurity objectives while urging that the new powers carry limits so they do not have unintended effects on privacy. He recommended a uniform necessity-and-proportionality standard for collecting personal information, notification of his office when an incident involves a material privacy breach, and safeguards on information shared outside Canada. At the Senate stage in May 2026 he acknowledged significant improvements Parliament had already made.

**Bill C-22 — the Lawful Access Act, 2026** remains proposed legislation. Introduced on March 12, 2026, it passed the House of Commons on June 18 after the government invoked time allocation to limit debate. As of this brochure's September 2026 snapshot it is before the Senate, which resumes on September 21 and has not yet begun its study.

The government describes lawful access as the ability of law enforcement or the Canadian Security Intelligence Service to obtain information or intercept communications when legally authorized. Part 2 of Bill C-22 would enact the Supporting Authorized Access to Information Act, requiring electronic service providers to maintain the technical capabilities needed to give effect to those authorities.

Government and critics describe the safeguards differently. A spokesperson for the Minister of Public Safety has said the bill would not require companies to build backdoors, and that authorities would still need legal authorization such as a court warrant to obtain data. Critics note that as introduced the bill would also let an officer with reasonable grounds to suspect an offence require a telecommunications provider to confirm whether a person is a subscriber, without prior judicial authorization.

<!-- page: 4 layout=standard -->

Commissioner Dufresne told the House committee in May 2026 that privacy concerns remain, and made eight recommendations — among them narrowing the definition of subscriber information, limiting which providers can be compelled, and adding an overarching requirement that obligations be necessary and proportionate. Amendments later adopted reduced the maximum metadata-retention period from one year to six months and required the Minister to be satisfied that a retained category is essential to investigations.

## Why VPN Providers Care

For a VPN provider built around encryption and a no-logs design, a requirement to create new technical access or data-retention capabilities raises a direct question: can the provider comply without changing the privacy properties it promises its customers?

NordVPN said on May 15, 2026 that it was reviewing Bill C-22, and that if it became subject to mandatory obligations it would not compromise its no-logs architecture or encryption protections. It would instead consider all viable options, including limiting or removing its presence from Canadian jurisdiction. That was a conditional warning, not an announced departure.

Windscribe, which is headquartered in Canada, was blunter. It said the previous day that it would leave the country if the bill passes, noting that a company based elsewhere can simply switch off its Canadian servers while its own head office is here. The encrypted messaging service Signal had said earlier that week that it would rather withdraw from the Canadian market than comply.

These are stated positions, not outcomes. The project does not predict what Parliament, regulators or VPN providers will ultimately do. It provides a privately hosted architecture in which the user's own connection to **Your VPS** remains separate from the commercial VPN provider running beyond it.
