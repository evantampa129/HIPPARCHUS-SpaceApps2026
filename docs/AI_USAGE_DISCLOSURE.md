# AI usage

We used generative AI tools during the hackathon. This is what they did and what they did not do.

**What AI helped with**
- **Visuals:** the HIPPARCHUS and AETHENOVA logos and banner are AI-generated. Every copy we publish carries a visible
  "AI-generated" mark (`presentation/assets/*_ai.png`).
- **Video:** assembling and editing the demo video (layout, captions, timing). The footage in it is real screen
  recordings of our app and real SPHEREx images; scenes that are illustrations are labelled as such.
- **Code:** an AI coding assistant helped write and refactor code, tests and build scripts.
- **Methods and writing:** reviewing the methods, checking references against doi.org, and drafting text for the
  README, report and slides.

**What AI did not do**
- It did not produce any measurement. Every number comes from running our code on real SPHEREx images from IRSA, and
  each one is stored with checksums in `submission/evidence/`.
- It did not validate the science. Validation is the automated test suite, the null tests, the SIMULATED
  injection-recovery tests and the stability checks, all reproducible with the scripts in `backend/scripts/`.
- We reviewed, ran and tested every piece of code before using it. We are responsible for every claim.

No NASA logos or insignia are used anywhere.
