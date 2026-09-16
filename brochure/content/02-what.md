<!-- page: 5 layout=standard -->

# What Snarkypuss Is

Snarkypuss is privately hosted, open-source software for building and controlling your own bridge to a commercial VPN service. It is not itself a VPN provider, and there is no Snarkypuss company, subscription service, or central network carrying users' traffic.

You provide two things: your own hosted virtual server and your own account with a supported commercial VPN provider. Snarkypuss supplies the software that connects them and gives you a private control interface for managing the result.

Each installation belongs to its user. The server is under that user's control, the commercial VPN relationship remains between the user and the VPN provider, and Snarkypuss does not change the legal obligations of either.

In short, Snarkypuss is:

- privately hosted
- open source
- non-commercial
- operated on your own VPS
- used with the VPN provider you choose separately
- intended for lawful use

<!-- page: 6 layout=spread-left -->

# The Basic Idea

The route is simple to describe.

<!-- diagram: basic-idea height=150mm -->

<!-- page: 7 layout=spread-right -->

Your PC first connects to **Your VPS** through WireGuard, an encrypted point-to-point tunnel. The commercial VPN software runs on the VPS rather than directly on your PC. Internet traffic arriving through WireGuard can then be forwarded through the commercial VPN connection before it reaches the public Internet.

Your VPS (Virtual Private Server) is a small-footprint hosted virtual server. It provides the Internet-connected Linux environment Snarkypuss needs without requiring dedicated hardware. A suitable VPS costs approximately US$5 per month.

This creates two distinct relationships. The WireGuard tunnel between your PC and your VPS is private infrastructure that you control. The onward VPN connection is supplied by the commercial provider you have chosen. Snarkypuss sits between those two pieces and manages the gateway.

There is no shared Snarkypuss relay in the middle. Your traffic does not pass through a Snarkypuss-operated service.

<!-- page: 8 layout=standard -->

## Why Keep the Commercial VPN?

A VPS could send traffic directly to the Internet, but that would make the VPS itself the public exit point. Snarkypuss is designed to preserve the useful properties of a commercial VPN while moving that VPN connection onto infrastructure you control.

A commercial VPN can provide a large pool of shared exit servers, many geographic destinations, provider-operated network infrastructure, and convenient changes of destination. Those are services that a single low-cost VPS is not intended to reproduce.

So the VPS is primarily the private bridge. The commercial VPN remains the outward-facing privacy service.

Snarkypuss can also enter a deliberate **Direct VPS** mode in which traffic exits through the VPS without the commercial VPN, but that is an explicit exceptional state rather than a silent fallback.

## Meet Snarkypuss

For normal use, you do not administer the gateway by typing Linux or VPN commands. SnarkyCtl, the management component of Snarkypuss, provides a private web dashboard reached through the WireGuard tunnel.

<!-- page: 9 layout=standard -->

The dashboard shows the effective state of the gateway: whether the upstream VPN is protected or disconnected, the current VPN target and server, the public Internet address being used, and the state of important protections such as leak protection and DNS. Status is refreshed automatically while the dashboard is open.

From the same interface you can choose a destination and ask Snarkypuss to connect or disconnect the commercial VPN. The dashboard exposes defined Snarkypuss operations rather than a general-purpose administrator console.

## Choosing Where You Connect

A VPN destination in Snarkypuss is called a **target**. Targets are approved choices in the target catalogue, not arbitrary command-line arguments passed to the VPN software.

One choice is always available: **Fastest available server**. This is the provider's built-in recommended destination. It is a special Snarkypuss target and does not have to be added to the catalogue before it can be selected.

For more control, the catalogue can contain provider-supported choices such as a country, city, server group, or a specific server. A fresh installation does not invent any of these choices for you; you add the destinations you actually want to use.

Snarkypuss can discover available destinations from the installed VPN provider rather than depending on a server list frozen into the application. If a previously saved destination is no longer available, Snarkypuss does not silently substitute a different one.
