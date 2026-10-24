# Japan wearables and a focused product direction

Research checked 24 October 2026. These are proposals for discussion, not an expansion of the implemented V1 scope. Manufacturer capabilities below are documented; no physical glasses, speech API or wearable application was tested. The connected app currently accepts PDF, image and text evidence, not raw audio/video.

## Recommended direction

Help equipment-finance inspection teams finish a useful inspection in one visit and explain what would get idle equipment into use. The proposed differentiator is a **before-you-leave evidence check**, with short voice-linked field notes and practical blocker follow-ups. Capture enough evidence or assign the remaining gap clearly; do not require every claim to become supported before leaving or completing review.

This uses the existing backend's atomic claims, mission/checklist, context records, deterministic next actions and follow-ups. The new work would be the capture/voice interaction and guided end-of-visit handoff. More recording alone does not make the business stronger.

## Relevant hardware shortlist

| Device | Verified capability | Relevance and qualification |
|---|---|---|
| Japan-made InfoLinker3 / FieldX | Camera photo/video capture, two-microphone noise cancellation, voice operation, LTE, swappable battery and field-oriented enclosure | Strong industrial fieldwork candidate. Existing LinkerWorks already supplies remote support and work navigation, so those features alone are not a differentiation. Custom integration access/terms need vendor confirmation. [Manufacturer](https://www.fieldx.co.jp/infolinker3/) |
| Japan-made MiRZA / NTT QONOQ Devices | Wireless phone-linked XR; manufacturer camera/microphone development samples, microphone capture and speech-to-text demonstration | Good Japan-specific AR prototype candidate. Requires a supported phone; the product page lists roughly 1–1.5 hours under heavy camera/display use. [Product](https://www.xr.docomo.ne.jp/mirza/xrd-t01/), [developer FAQ](https://www.xr.docomo.ne.jp/developer/doc/1.0.3/faq/) |
| RealWear Navigator 520 | Industrial voice operation, camera/video and microphones; documented developer examples for camera and microphone control | Practical industrial comparison, not a Japanese-made device. Japan is an approved market. Voice command and audio recording access need coordination; the official developer examples discuss releasing the microphone. [Japan approval](https://www.realwear.com/legal/approved-countries), [hardware/audio](https://support.realwear.com/knowledge/know-your-device), [developer examples](https://github.com/realwear/devdocs/blob/main/docs/developer-examples/developer-examples-tutorial.md) |
| XREAL One series + XREAL Eye | Japan product page documents first-person photo/video capture; current RGB SDK documentation supports real-time camera access/recording with Eye | Potential spatial checklist/capture prototype. The camera accessory matters: spatial tracking sensors on other glasses are not automatically inspection cameras. Hardware/phone/SDK compatibility must be tested together. [Japan product](https://www.xreal.com/jp/eye), [RGB SDK](https://docs.xreal.com/Camera/Access%20RGB%20Camera) |
| Ray-Ban Meta camera models | Japanese manufacturer release confirms Gen 3 sale on 24 September 2026, with camera capture and a six-microphone array | Consumer capture candidate, not industrial PPE. Meta's official Android sample documents photo/video/live camera access and optional microphone sound in video; test supported model, firmware, region and developer enrollment before selecting. Do not confuse camera models with audio-only glasses. [Japan manufacturer release](https://prtimes.jp/main/html/rd/p/000000084.000005515.html), [official SDK sample](https://github.com/facebook/meta-wearables-dat-android/blob/main/samples/CameraAccess/README.md) |
| Japan's Fairy Devices THINKLET | Android-compatible neck-worn camera device with five-channel microphone SDK access and standalone LTE | Not glasses, but especially relevant for audio-focused field capture. Its developer portal lists camera preview, multichannel video recording and barcode examples. This is an alternative form factor, not an extra device the POC needs. [Developer portal](https://fairydevicesrd.github.io/thinklet.app.developer/), [microphone SDK](https://github.com/FairyDevicesRD/thinklet.app.sdk) |

The useful advances are accessible first-person camera feeds, improved wearer audio, programmable interactions and lightweight spatial displays. They make contextual capture more practical. They do not themselves establish asset identity, installation, commissioning, financial truth or the identity of a speaker. For the hackathon, use an existing phone/webcam to demonstrate the interaction before buying hardware.

## What audio can add

The most useful interpretation of audio tracking is **which statement belongs to which machine and capture time**. The inspector selects/confirms CNC-003, records a short note with a photo, names the source role, and checks the resulting transcript. Keep the original audio, exact transcript and edited summary distinct when audio storage is added. Speaker separation and sound-direction localization are different capabilities and were not verified across these products. Do not present an operating sound as evidence of commissioning or use it to diagnose machinery in this POC.

Noise-cancelling wearable microphones often emphasize the wearer; clear capture of a manager across a noisy room cannot be assumed. Use deliberate short recordings with permission and test the actual sound. Multilingual transcription/translation can be helpful, but retain the original and have an analyst check identifiers and statements.

Assuming the intended tool is **Wispr Flow**: its official guide supports external microphone selection/routing, so dictating into the existing observation text field is a plausible manual trial. This was not tested with glasses. A glasses microphone must actually appear as a usable input; Bluetooth support alone does not guarantee that route. [Microphone guide](https://docs.wisprflow.ai/articles/8884408990-connect-and-set-up-external-audio-devices)

There is an official [Flow API portal](https://platform.wisprflow.ai/). Account access, pricing, supported ingestion/streaming functions and integration were not verified. Its [MCP connector](https://docs.wisprflow.ai/articles/9551372685-connect-an-mcp-client-to-wispr-flow-remote-mcp-server) reads existing notes/meetings; it is not a live glasses recorder. Do not substitute an unofficial reverse-engineered API for a supported production integration.

## Small adjacent problems worth solving

| Problem | Proposed solution | Priority |
|---|---|---|
| Photos and comments get associated with the wrong machine | Short voice-linked capture: confirm machine ID, save photo, record source-labelled explanation and time together; analyst checks the association | Build with the next capture slice |
| The office discovers a missing shot after the inspector has left | Before-you-leave check that distinguishes a capture possible now, a document request and an unresolved physical assessment | Main differentiator to demonstrate |
| Packaged/idle equipment is flagged but no one knows what happens next | Ask what is blocking installation, record it as a contextual explanation, assign an owner and requested completion evidence | Main business-value extension |
| One missing certificate delays the whole file | A narrowly scoped, controlled request to the supplier/commissioning engineer for that machine's missing document, with later analyst review | Later extension; current follow-up records are the foundation |
| Repeat visits redo all earlier paperwork | Show what changed since the last inspection and request fresh physical evidence while retaining unchanged document history | Later; needs cross-inspection identity/freshness design |

## Concrete demonstration

CNC-003 is packaged. The inspector records a photo and a short statement: the plant manager says installation is waiting for an electrical connection. The system proposes a blocker explanation and a follow-up for the responsible owner. Installation and commissioning remain unresolved. Before leaving, the inspector sees that the physical visit evidence is collected and the remaining action has a clear owner and evidence request. Later, installation records and a commissioning certificate can be reviewed through the existing acceptance/reconciliation flow.

This is a proposed hypothetical scenario, not a fact observed about the seeded demo. It makes the product useful to the plant as well as the reviewer: the assessment explains the gap and the next practical action without turning a statement into proof.

## Stronger business case to validate

Initial buyer: equipment-finance inspection operations, working with their surveyors. End user: the field inspector and reviewing analyst. Sell a consistent, reviewable equipment inspection and gap-closing workflow, priced per inspection with volume contracts. Existing phones remain supported; a glasses vendor is a capture partner, not a dependency for the business.

The customer hypothesis is fewer repeat visits, less report preparation and faster resolution of incomplete files. Validate it with paid pilots and measure repeat-visit rate, time to accepted report, reviewer clarification requests and time to close installation/document blockers. Do not claim a savings percentage or proven demand before measuring it.

The defensible work is the machine/evidence history, six-claim rule templates and field-to-review handoff. Basic camera capture, AR overlays, translation, dictation and remote calls already exist; the proposal does not claim to be a first-ever invention. Keep the next demo to voice-linked notes, the end-of-visit check and one blocker follow-up. Broad predictive maintenance, always-on recording, biometric speaker identification and automatic lending decisions are outside this proposal.
