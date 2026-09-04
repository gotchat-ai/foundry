=== GotChat Framework Release ===

Name: GotChat Foundry Framework Release
Contributors: thy.nguyen
type: framework
Version: 1.0.4
License: Apache 2.0

Core release for the GotChat Foundry platform. Go to the website gotchat.ai and check out the setup tutorials.

== Description ==
This package contains the main GotChat release.

== Installation ==
1. Upload the release archive in the admin release area.
2. Apply the release to the target environment.
3. Restart the affected services if required.

== Screenshots ==
1. ss1.png
Model Deck 1
2. ss2.png
Model Deck 2

== Requirements ==
- Valid GotChat deployment target
- Matching service/runtime components when required
- Backup recommended before upgrade

== Server Requirements ==
- Modern Windows or Linux host, or Mac environment
- Sufficient CPU, RAM, and storage for the deployed stack

== Client Requirements ==
- Modern web browser for admin and user access

== Special Note On Requirements ==
This release should be deployed with compatible backend services, CMS components, and runtime dependencies for the same release line.

== Changelog ==
= 1.0.4 =
- File changes
- Improved video/image LLM workflow resource cleanup and move it into worker process

= 1.0.3 =
- File changes
- Refractored app.py
- improve video/image llm and added workflow capability to it (base on ComfyUI-GGUF loader but running off its own independent node lifecycle) 

= 1.0.2 =
- Made some changes to readme
- added vllm_backend_2.py file
- added a newline after import torch line
