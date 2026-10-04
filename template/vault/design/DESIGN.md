---
title: Design system (DESIGN.md)
type: design
status: draft
owner: designer
updated: {{DATE}}
summary: The one locked design file - tokens for colour, type, spacing, radii and components. Draft until the owner approves it.
tags: [design, tokens]
version: alpha
name: Draft design system
description: Placeholder tokens. The Designer replaces them at the first design step.
colors:
  primary: "#2F5D50"
  on-primary: "#FFFFFF"
  neutral: "#F6F6F4"
  text: "#1B1B1A"
  muted: "#5F5F5A"
  danger: "#B3261E"
typography:
  body-md:
    fontFamily: system-ui
    fontSize: 16px
    fontWeight: 400
    lineHeight: 1.5
  heading-lg:
    fontFamily: system-ui
    fontSize: 32px
    fontWeight: 600
    lineHeight: 1.2
rounded:
  sm: 4px
  md: 8px
spacing:
  sm: 8px
  md: 16px
  lg: 32px
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    rounded: "{rounded.md}"
    padding: "{spacing.sm}"
---
<!-- Google DESIGN.md format: tokens live in the header above (alongside the vault's page fields).
     Spec: npx --yes @google/design.md spec   Lint: npx --yes @google/design.md lint design/DESIGN.md
     No colour, font or spacing in the product exists outside these tokens. -->

## Overview
_Draft. What the product should feel like, in two lines, once the owner has picked a direction._

## Colors
- **Primary (#2F5D50):** the one action colour.
- **Neutral (#F6F6F4):** page background.

## Typography
System fonts until a direction is chosen.

## Layout
An 8px spacing scale.

## Components
One primary button style.

## Do's and Don'ts
- Do: use only the tokens above.
- Don't: anything on [[design/anti-slop]].
