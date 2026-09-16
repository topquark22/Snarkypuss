<!-- page: 10 layout=spread-left -->

# Privacy Includes Failure

Connecting successfully is only the happy path. A privacy gateway also has to answer a more important question: **what happens when something goes wrong?**

The commercial VPN can disconnect. A connection attempt can fail. Routing can be incomplete. DNS can be misconfigured. A service can restart after an upgrade or reboot. And sometimes the software may be unable to establish with confidence what route traffic is actually taking.

Snarkypuss therefore describes the effective gateway state rather than treating a successful connect command as proof that the connection is safe.

<!-- diagram: states height=78mm -->

<!-- page: 11 layout=spread-right -->

**Protected VPN** is the normal state. Internet traffic arriving through WireGuard is forwarded through the commercial VPN, and Snarkypuss can verify the expected protected route.

**Locked** is the safe disconnected state. Public Internet forwarding is blocked. You can still reach the private SnarkyCtl interface through WireGuard, but ordinary Internet traffic is not allowed to escape through the VPS simply because the commercial VPN is unavailable.

**Direct VPS** is an explicit exceptional mode. It deliberately allows Internet traffic to leave through the VPS public connection without the commercial VPN. This can be useful for administration or troubleshooting, but it is not presented as VPN-protected traffic and it is never intended to become the automatic fallback from a failed VPN connection.

**Unknown** means exactly that: Snarkypuss cannot establish the effective safety state with sufficient confidence. It does not turn uncertainty into a reassuring green light.

<!-- keyline: Loss of the upstream VPN must not silently become an unprotected Internet connection. -->

<!-- page: 12 layout=spread-left -->

# Under the Hood

The internal design separates two ideas that are easy to confuse: controlling the gateway, and carrying Internet traffic through it. They are not the same path.

## SnarkyCtl Control

<!-- diagram: architecture-control height=112mm -->

<!-- page: 13 layout=spread-right -->

## Network Gateway

Internet packets arriving through WireGuard follow the routing and DNS configuration to the provider VPN and then onward to the Internet. They do **not** pass through the SnarkyCtl web application.

<!-- diagram: architecture-gateway height=86mm -->

Your browser reaches the dashboard through the private WireGuard connection, and operations that genuinely require administrator access are performed by a restricted privileged control service. SnarkyCtl controls and observes the provider connection, but it sits beside the packet path rather than inside it.

The reference deployment runs on Linux on a privately controlled VPS, and the architecture is intentionally provider-independent.

<!-- page: 14 layout=standard -->

## More Than `nordvpn connect`

At first glance, Snarkypuss can sound like a very small project. Install WireGuard on a VPS, forward some packets, put a web page in front of commands such as `nordvpn connect`, and the job appears to be finished.

That describes the demonstration. It does not describe a dependable gateway.

A real system has to coordinate several pieces of networking state. WireGuard must remain reachable while the upstream VPN changes routes. IP forwarding has to send traffic to the correct interface. DNS has to follow the intended path. Firewall and leak-protection rules must agree with the selected operating mode. The software has to distinguish a provider that is disconnected from one that is connected but not actually carrying traffic as expected.

Destinations introduce another problem. VPN providers change their networks, so Snarkypuss discovers the provider's current choices instead of assuming that an embedded server list stays correct.

Then there is lifecycle engineering: installation, configuration, upgrades, service startup, reboots, database changes and recovery from mistakes. A networking tool that works only until the next reboot is not much of a gateway.

None of these problems is individually exotic. The complexity comes from making them work together while preserving one simple promise: the dashboard should report the route that Snarkypuss can actually verify.
