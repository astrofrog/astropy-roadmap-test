# The Astropy Roadmap

**Latest revision: October 2026 (draft)**

- [Introduction](#introduction)
- [How to read this document](#how-to-read-this-document)
- [Functionality](#functionality)
- [Infrastructure and Documentation](#infrastructure-and-documentation)
- [Interoperability and Compatibility](#interoperability-and-compatibility)
- [Hardware and Performance](#hardware-and-performance)
- [Learn and User Support](#learn-and-user-support)
- [Community Building and Sustainability](#community-building-and-sustainability)
- [Governance, Management, and Personnel](#governance-management-and-personnel)
- [Fund Raising](#fund-raising)

See the [Roadmap Completed Items](COMPLETED.md) page for objectives that have been completed and removed from the roadmap.

## Introduction

This Roadmap captures the high level objectives that the Astropy Project aims to achieve to improve the health and stability of the Project, together with the key results we will use to measure progress towards each objective. It is maintained by the Strategic Planning and Organizing Committee (SPOC) and is revisited at least once a year at the Astropy coordination meeting, and at any time via pull requests to this repository.

The Roadmap is used to prioritize the allocation of Project resources. In particular, funding requests submitted in response to the Project's funding calls are asked to identify which key results they address.

## How to read this document

The Roadmap is organized into the same categories as previous versions. Within each category, each **objective** is a qualitative goal that describes a state we want the Project to reach. Each objective has up to five **key results**: concrete, measurable outcomes that, taken together, tell us whether the objective has been achieved. A key result is a single sentence that contains its own measure of success, for example a number, a published document, or a merged and released feature.

Every objective has an identifier such as `O3` and every key result has an identifier such as `R3.2`. Identifiers are stable: once assigned they are never renumbered or reused, so they can be cited in funding requests, issues, and pull requests without ambiguity. New objectives take the next unused number regardless of their category.

This file is the authoritative statement of what the Project has agreed to aim for, and changes to it are made by pull request. Progress tracking and discussion happen in a GitHub issue per objective, with one sub-issue per key result, linked from the `Tracking` line under each objective. The issues are where status updates, links to funded work, and links to implementation pull requests in other repositories belong. When all key results of an objective are complete, the objective is moved to the completed items page and its issue is closed.

Each objective carries a priority (high, medium, or low) assigned by the SPOC. Priority reflects how important the SPOC considers it that progress is made before the next revision, independent of whether anyone is currently working on it.

## Functionality

The core product of the Astropy Project is high quality astronomical software, including both the core library and Astropy Affiliated packages. This category encompasses goals having to do with this core Project functionality.

### O1 Improve support for reading and writing ASDF files, optionally with GWCS coordinates, in the astropy core and coordinated packages

- **R1.1** Publish a table listing, for the core and coordinated packages, every function and method that accepts FITS files as input or output, either as filenames or as HDU objects, and whether it also accepts ASDF filenames or objects.
- **R1.2** Publish a list of the cases where support for ASDF and GWCS is not currently possible without significant upstream work in astropy, asdf-astropy, or the ASDF standard.
- **R1.3** Add support for ASDF and GWCS in at least 90% of the remaining cases where this is technically feasible given the current ecosystem.

### O2 Develop and implement a modern and maintainable strategy for FITS that improves performance and capabilities

- **R2.1** Publish an APE outlining the plan to improve the performance and long-term maintainability of FITS support within the Astropy Project.
- **R2.2** Develop a set of benchmarks that encapsulate the performance targets we want to achieve, for example constant time to open files as file sizes grow.
- **R2.3** Make astropy's FITS support competitive with other packages as measured by the benchmarks in R2.2.
- **R2.4** Increase the number of active FITS maintainers to at least two and decrease the mean age of open FITS-related issues by one month.
- **R2.5** Ensure that new FITS-related issues receive a response within one release cycle.

### O3 Provide support for reading and writing spectra using the IVOA SpectrumDM in specutils

- **R3.1** specutils can read any SpectrumDM-compatible VOTable, demonstrated using at least one spectrum downloaded from each of at least two different archives.
- **R3.2** specutils can write a Spectrum object to a SpectrumDM-compliant VOTable given sufficient metadata, including validation that gives feedback to the user when the metadata is insufficient.
- **R3.3** Reading and writing as in R3.1 and R3.2 are demonstrated, including validation, for both the FITS and the XML serializations specified by SpectrumDM.

### O4 Make astropy.units.Quantity a modern part of the Python array ecosystem by supporting any array-API-compliant backend

- **R4.1** A new Quantity class that wraps any array-API-compliant array is merged to main with a stable, documented public API, building on the existing prototype.
- **R4.2** The Quantity test suite runs in CI against NumPy and at least three other backends, including array-api-strict with a non-CPU device, with at least 90% of the suite passing for each.
- **R4.3** All core array-API operations on Quantity, including arithmetic, ufuncs, indexing and broadcasting, produce correctly unit-propagated results for every tested backend.
- **R4.4** Every Quantity behaviour that assumes NumPy array internals and conflicts with array-API compliance is deprecated, each with a migration note in the changelog.
- **R4.5** An "Array backends" guide is published in the astropy documentation with end-to-end worked examples for each supported backend, covering unit-aware computation and device transfer.

### O5 Increase the user base of specutils and specreduce, including individual researchers and larger institutional users such as observatories, surveys, and missions

- **R5.1** Publish a set of tutorials demonstrating the use of specutils for common spectroscopy tasks.
- **R5.2** Advertise specreduce and its tutorials to observatories and instrument teams and record which have adopted it.

### O6 Provide supported, public ways of serializing astropy objects

- **R6.1** Publish a list of astropy classes together with whether, and how, each can currently be serialized.
- **R6.2** Decide on and document a single supported serialization approach, taking into account the existing representation dictionaries in astropy core, astropydantic, and the pydantic integration in stellarphot.
- **R6.3** Implement the chosen approach for every class in the list from R6.1 that is not already covered.

## Infrastructure and Documentation

Underlying all Astropy packages is critical infrastructure that ensures high quality, well-documented software is released. This category encompasses goals having to do with such infrastructure and documentation.

### O7 Improve the robustness and reliability of performance benchmarking

- **R7.1** Set up a GitHub self-hosted runner on dedicated hardware, where benchmarks can be bound to a specific core, with full documentation of how it was set up.
- **R7.2** Switch the astropy core benchmarking job to this runner and demonstrate stable timings in line with local dedicated hardware.
- **R7.3** Document how to set up similar benchmarking jobs in other packages in the astropy organization and advertise this to coordinated package maintainers.

### O8 Identify single points of failure throughout the infrastructure of the Astropy ecosystem

- **R8.1** Complete and publish an audit listing each piece of infrastructure, including bots, CI runners and automation, together with the people who can operate it.
- **R8.2** Ensure that every item in the audit has at least two people able to operate it, or an open issue tracking the recruitment of a second person.

### O9 Develop a process and infrastructure to test support for the data formats of new major missions

## Interoperability and Compatibility

One of the core principles of the Astropy Project is to "foster an ecosystem of interoperable astronomy packages." This category encompasses goals related to that principle of interoperability and compatibility.

### O10 Increase the visibility and usage of coordinated packages beyond the core package

- **R10.1** Make it possible to install groups of ecosystem packages by use case, for example `pip install astropy[photometry]` or `pip install astropy[spectroscopy]`.
- **R10.2** The astropy.org landing page highlights the ecosystem and lets visitors navigate coordinated and affiliated packages by use case or domain rather than only presenting the core package.
- **R10.3** Usage metrics, such as web analytics on documentation pages, are tracked for every coordinated package.
- **R10.4** Monthly documentation traffic for at least three coordinated packages is 50% higher than when tracking started.

### O11 Improve interoperability between unit packages such as astropy.units, pint, unyt, and unxt

- **R11.1** Define and publish a units API so that developers can write units-aware code that is agnostic to the unit package.
- **R11.2** Implement conversion mechanisms between astropy.units and at least two other unit libraries.

### O12 Improve and maintain interoperability with performant I/O file formats and libraries

- **R12.1** Astropy tables and NDData objects can be read from and written to HDF5 and zarr, and can wrap Dask arrays, with each combination covered by tests.

## Hardware and Performance

Astronomers perform their work in a variety of computing environments with a variety of requirements. This category encompasses goals related to supporting the performance and hardware needs of Astropy Project users, as well as anticipating future needs and requirements.

### O13 Identify the barriers to making Astropy work easily in non-cloud HPC contexts

- **R13.1** Review and categorize the HPC-related issues already reported across the astropy organization.
- **R13.2** Develop and carry out a survey of HPC users to identify the challenges they face when using Astropy.
- **R13.3** Every barrier identified in R13.1 and R13.2 has an open issue in the relevant repository.
- **R13.4** Publish a list of major HPC users of Astropy, based on survey responses, who can be consulted on future work.

### O14 Identify the barriers to making Astropy work easily in cloud contexts

- **R14.1** Review and categorize the cloud-related issues already reported across the astropy organization.
- **R14.2** Develop and carry out a survey of cloud users to identify the challenges they face when using Astropy.
- **R14.3** Every barrier identified in R14.1 and R14.2 has an open issue in the relevant repository.
- **R14.4** Publish a list of major cloud users of Astropy, based on survey responses, who can be consulted on future work.

### O15 Identify the places in astropy core where GPU support would be beneficial and design a plan for supporting them

### O16 Add basic support for JIT compilation, for example with numba or JAX, in astropy core and coordinated packages

## Learn and User Support

The Astropy Project cannot succeed in its core objectives without a robust user onboarding and support system. This category is for items related to the Astropy Learn ecosystem and other user support related improvements.

### O17 Expand and build on workshop offerings, including online delivery and increased geographic coverage

- **R17.1** Produce an online, self-paced version of the regular Astropy workshop tutorial.

### O18 Identify ways in which we can improve the experience of astronomers using LLMs with Astropy

## Community Building and Sustainability

As a community-driven project, the long term health and development of the Astropy community is an intrinsic part of the Project. This category encompasses goals related to growing and maintaining that community, and ensuring that it adheres to the core principles of inclusion and consensus-building.

### O19 Develop a sustainable and recurring mechanism for measuring and understanding the Astropy user and developer communities, and for identifying gaps in the ecosystem for common astronomy tasks

- **R19.1** Establish or assign a committee or designated role with explicit responsibility for tracking the health of the Astropy user and developer communities.
- **R19.2** Define a set of community health indicators for both the user and developer communities, covering for example demographics, use cases, needs, contributor statistics, and satisfaction.
- **R19.3** Run a user survey on a recurring cadence, for example every two years, that measures the indicators in R19.2 and collects feedback on missing functionality.
- **R19.4** Translate the missing functionality identified in R19.3 into new objectives and key results in this Roadmap.

### O20 Improve the sustainability and maintenance of coordinated and affiliated packages

### O21 Identify ways in which we can ensure the wellbeing of our community in the age of LLMs

## Governance, Management, and Personnel

This category encompasses goals related to governing and managing the Astropy Project to facilitate reaching the goals described elsewhere in this document.

### O22 Create a process to identify and ensure progress on longstanding issues that should be high priority

- **R22.1** Establish or assign a committee or designated role with explicit responsibility for identifying longstanding high-priority issues and overseeing progress on them.
- **R22.2** Produce an initial list of longstanding high-priority issues and translate them into objectives and key results in this Roadmap.
- **R22.3** Review progress on these issues at least yearly at the coordination meeting.

### O23 Identify ways in which we can leverage LLMs to help with the sustainability of the Project

## Fund Raising

To ensure project sustainability, the Astropy Project needs funding sources that can be maintained over the long term.

### O24 Raise funds from governmental sources outside of the US

### O25 Raise funds from private foundations
