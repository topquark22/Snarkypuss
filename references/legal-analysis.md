# Bill C-22 as it pertains to Snarkypuss

## Scope

This brief examines the June 18, 2026 XML version of Bill C-22 supplied for review. It focuses on Part 2, which would enact the **Supporting Authorized Access to Information Act**. Unless stated otherwise, section references below refer to that proposed Act, not the section numbers of Bill C-22 itself.

This is a reading of the supplied legislative text, not a legal opinion or a statement that the proposal has become law. It does not assess later amendments, future regulations, or authorities under other legislation.

## The legal question: Could the VPS itself qualify as a “provider”?

**The VPS is the infrastructure through which the service operates; the statutory question concerns the person or entity providing the service.** A virtual machine is not ordinarily a legal person and does not become a provider merely because it transmits information. Its operator could, however, qualify as an **electronic service provider**. The hosting company may separately provide its own covered service; that would not automatically settle the status of the Snarkypuss operator.

The proposed Act does not define a special category called “privacy service.” Section 2(1) instead defines:

- **Electronic service:** broadly, a service or service feature involving activities such as creating, storing, processing, transmitting, or receiving information by technological means.
- **Electronic service provider:** a person who, individually or as part of a group, provides an electronic service, including for enabling communications, and either:
  - “provides the service to persons in Canada”; or
  - “carries on all or part of its business activities in Canada.”

Operating a VPN gateway fits the technical activities described in “electronic service.” The harder question is whether a particular operator is **providing a service to persons**, especially when the operator is also the sole user.

The Canadian-service alternative does not expressly require payment, commercial activity, public availability, or a minimum number of subscribers. Hosting the VPS outside Canada is therefore not, by itself, an exclusion where the operator provides the service to users in Canada.

## Case 1: The individual operates the VPS exclusively for personal use

### Facts assumed

An individual operates a Snarkypuss gateway on a VPS. Only that individual uses it, through their own devices. They do not offer accounts or gateway access to anyone else. The individual uses the service from Canada.

### Analysis

There is a reasonable distinction between **using one's own equipment or infrastructure** and **providing an electronic service to other people**. On that reading, a person using a private VPN solely for themselves is a user of their own system, rather than a service provider serving customers or other users.

However, section 2(1) does not expressly say “other persons,” and it contains no express personal-use or self-hosting exemption. The supplied text therefore does not conclusively resolve whether self-provision falls within the definition. The plural word “persons” should not, by itself, be treated as establishing a minimum-user exemption.

Multiple devices used by the same individual do not, by themselves, turn this scenario into an offering to multiple users.

### Conclusion for the individual

**The text does not clearly establish that an exclusively personal Snarkypuss installation is covered, but it also does not expressly exempt it.** It would be premature to tell the individual either that they must implement logging or that their installation is categorically outside the Act.

The precise question for legal clarification is:

> Does a natural person who operates a private VPN exclusively for their own use “provide[] the service to persons in Canada” within section 2(1), or does that language require provision to a person other than the operator?

The mere act of using Snarkypuss is not expressly prohibited, and the supplied text does not automatically impose a universal logging obligation on every private gateway.

## Case 2: The individual offers the VPS as a service to multiple users

### Facts assumed

The operator gives other people access to the Snarkypuss gateway. At least some users are in Canada. Access could be provided privately to friends or family, or commercially to customers.

### Analysis

This is a substantially stronger case for **electronic service provider** status: a person is operating a communications service and providing it to other people in Canada.

The definition does not expressly require a fee or a public offering. Consequently:

- Free access is not an express exemption.
- Restricting access to friends or family is not an express exemption.
- Serving only a small number of users is not an express exemption.
- Using an overseas VPS is not an express exemption where Canadian users receive the service.

Section 48 permits regulations to distinguish providers by service type and the number of people in Canada they serve. That allows differentiated treatment, but does not itself create a small-provider exemption.

If nobody receives the service in Canada, the alternative test concerning business activities in Canada would still need to be considered. Canadian citizenship alone is not the territorial test stated in the definition.

### Conclusion for the operator

**Offering gateway access to other Canadian users creates a materially stronger basis for coverage than exclusive personal use.** The potentially regulated party is the operator or operating entity, not the virtual machine itself. Specific obligations would still depend on the applicable statutory provision, regulations, requests, or orders.

## What coverage would—and would not—mean

### Coverage is not an automatic requirement to log all traffic

The proposal distinguishes an **electronic service provider** from a **core provider**:

- Under sections 2(1) and 5, core providers belong to classes listed in a schedule that can be amended by regulation. The Core Providers schedule in the supplied XML contains no listed classes.
- Section 5(2) permits regulations concerning access capabilities, equipment, notices, and retention of specified metadata for reasonable periods not exceeding six months.
- Sections 5(4) and 5(4.1) constrain that metadata-retention regulation power, including exclusions for communication content, browsing history, and social-media activities, and an essentiality requirement.

These provisions do not themselves order every Snarkypuss user to start recording traffic.

### Non-core status is not a complete exclusion

Section 7(1) permits an individual ministerial order containing provisions of the kinds allowed under section 5(2), **“whether or not the provider is a core provider.”** Such an order requires Intelligence Commissioner approval, an opportunity for representations, and a validity period no longer than two years. Feasibility, cost, privacy, and cybersecurity are factors the Minister must consider.

Section 13 separately requires reasonable assistance with assessment or testing on a written ministerial request; that assessment or testing must not grant access to personal information. Not every obligation under the proposed Act depends on core-provider status.

### Encryption is relevant, but not a blanket exclusion

Section 2(4) restricts compelled decryption of user-encrypted information unless the provider supplied the encryption and possesses the information needed to decrypt it.

For Snarkypuss, terminating a WireGuard tunnel is different from decrypting the HTTPS connections carried inside it. The gateway's ability to handle the tunnel does not ordinarily give it HTTPS session keys. Whether a particular demand falls within the statutory exception would depend on the encryption layer and the operator's actual capabilities.

Sections 5(5), 7(5), and 24(2.1) protect against compelled systemic vulnerabilities. The statutory definition has a qualification concerning risks confined to information relating to persons subject to lawful access authorities; it is not an absolute prohibition on every targeted access mechanism.

## Could an ISP be required to block the individual's access?

**No express provision in the supplied bill requires ISPs to block Snarkypuss, private VPN users, WireGuard, or VPN traffic generally.** The text does not identify use of a private encrypted tunnel as a contravention.

Section 24 allows compliance orders requiring a provider to stop a contravention or take necessary compliance or mitigation measures. This is broad language tied to an underlying statutory obligation. It is not an express, free-standing power to order an ISP to block a third party's VPN. Such an interpretation would require an additional legal basis and argument; it is not established merely by the wording reviewed here.

The bill preserves existing access authorities under other legislation. This finding therefore does not establish that blocking could never be authorized under another law or a different legal process.

## Summary

| Question | Exclusive personal use | Service offered to other Canadian users |
|---|---|---|
| Is the VPS itself the legal provider? | Ordinarily no; examine the operator. | Ordinarily no; examine the operator or operating entity. |
| Could the operator be an electronic service provider? | Unresolved: the definition does not clearly address self-provision. | Substantially stronger basis for coverage. |
| Is unpaid or private use expressly exempt? | No express personal-use exemption. | No express free-service, friends-and-family, or small-service exemption. |
| Does the bill automatically require all traffic to be logged? | No. | No; distinguish possible coverage from specific obligations. |
| Could non-core providers receive individual orders? | Potentially, if they meet the provider definition. | Yes, section 7 expressly reaches non-core providers. |
| Does the supplied text expressly require ISP VPN blocking? | No. | No. |

**The central unresolved issue for an individual using Snarkypuss only for themselves is the meaning of “provides the service to persons in Canada.” Offering access to others makes the coverage argument considerably stronger. Neither scenario, by itself, establishes a duty to log all traffic or an ISP power to block VPN access.**

## Source

User-supplied `C-22_E.xml`, identified as the June 18, 2026 version of Bill C-22. Principal references: Part 2, clause 41, enacting the Supporting Authorized Access to Information Act, especially sections 2, 5, 7–13, 24, and 48, and its Core Providers schedule.
