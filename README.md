# Speedrun LSAT

**Exam: LSAT (Law School Admission Test), scored 120–180.**

An accelerated-learning study app for the LSAT, built as a brownfield fork of
[Anki](https://github.com/ankitects/anki). It ships a desktop app and an iOS
companion that share one Rust engine, makes a real change inside Anki's Rust
core (a schema-weighted study queue), and reports three separate scores —
memory, performance, and readiness — each with a range and a give-up rule.

See the product spec and roadmap in
[`docs/speedrun/PRD.md`](docs/speedrun/PRD.md) (architecture:
[`docs/speedrun/docs/architecture.md`](docs/speedrun/docs/architecture.md), roadmap:
[`docs/speedrun/docs/roadmap.md`](docs/speedrun/docs/roadmap.md)).

## License and attribution

This project is a fork of **Anki** by Ankitects Pty Ltd and contributors, and
is distributed under **AGPL-3.0-or-later**, the same license as Anki. Some Anki
components are under BSD-3-Clause. All original Anki copyrights and licenses are
retained. Anki is a trademark of Ankitects Pty Ltd; this is an independent fork
and is not affiliated with or endorsed by Ankitects.

---

# Anki (upstream)

[![Build Status](https://github.com/ankitects/anki/actions/workflows/ci.yml/badge.svg)](https://github.com/ankitects/anki/actions/workflows/ci.yml)
[![Documentation](https://img.shields.io/badge/docs-dev--docs.ankiweb.net-blue)](https://dev-docs.ankiweb.net)

This repo contains the source code for the computer version of
[Anki](https://apps.ankiweb.net).

## About

Anki is a spaced repetition program. Please see the [website](https://apps.ankiweb.net) to learn more.

## Getting Started

### Contributing

Want to contribute to Anki? Check out the [Contribution Guidelines](./docs/contributing.md).

For more information on building and developing, please see [Development](./docs/development.md).

#### Contributors

The following people have contributed to Anki: [CONTRIBUTORS](./CONTRIBUTORS)

### Anki Betas

If you'd like to try development builds of Anki but don't feel comfortable
building the code, please see [Anki betas](https://betas.ankiweb.net/).

## License

Anki's license: [LICENSE](./LICENSE)
