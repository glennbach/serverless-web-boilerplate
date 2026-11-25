# Proof

This repository holds the proof: a minimal web application with no product domain.

## Language

**Proof**:
The application in this repository. A browser interface and an HTTP API, used to demonstrate that the interface can call the API.
_Avoid_: Template, hello world, billing app, replacement

**Project**:
One copy of this repository, deployed under its own name. This repository's project is the Proof.
_Avoid_: Fork, app, stack

**Environment**:
One deployed instance of a project on AWS: QA or prod. Work on a laptop is local development, not an environment.
_Avoid_: Stage, stack, local environment, dev environment

**Current user**:
The person the proof shows as signed in. The API tells the interface who this is.
_Avoid_: Principal, account, claims
