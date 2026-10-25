# Public motor-nameplate demo registry

40 declarations from the user-supplied CDI_Motor_Nameplate_40 package. Publisher:
https://huggingface.co/datasets/sergiudanstan/motor-nameplate

Publisher labels are machine-generated and unverified. MTR tags and plant association
are synthetic. Fourteen serial labels are missing. Missing serials/invoice/payment
references are explicit placeholders, never accepted proof. All 240 claims start
unsupported and all imported files are unconfirmed, context-only evidence.

`assets.json` retains source metadata. Source filenames were resolved by unique
manufacturer/model matches (and serial where available) against the publisher's
metadata.csv. Thirty-seven resolve; three remain metadata-only. No ordinal-only
photo guesses were made. Original downloaded photos are runtime files and are not
redistributed in Git; underlying image rights require separate consideration.

Import into a running backend using a private environment file:

```powershell
python -m scripts.import_motor_nameplates --env-file <private-env> --photos <local-photo-directory>
```

The importer resumes an existing named registry, preserves other inspections,
adds missing assets/files/links, and creates its V2 case. Run one importer at a time.
It does not confirm evidence, declarations, site observations or physical identity.

MTR-031 is the scan fixture: General Electric, model 121123, serial 134678.
The unchanged source is 044.jpg; open its source-photo link in the Overview table
on another display, then capture it from the Android tablet. Its serial was
visually checked and independently read by local Tesseract. A new camera photograph
may need better focus/framing. Capture with MTR-031 selected. Exact unique OCR serial
association adds a context-only identity link; conflicts require review. The source
is not evidence that a machine exists at the demo site. No claim becomes supported
solely because the serial matches. Original scans and audit records remain intact.


The import also fills the operational manufacturer/rating/provenance fields used
by the editable registry and its manufacturer/model suggestions. Older imports
with nameplate metadata but empty operational fields receive a one-time upgrade;
subsequent runs preserve edited values. Registry corrections retain source
nameplate metadata unless explicitly replaced. The main overview shows the six
claims beside ratings and protected source-file links. `?inspection=<id>&asset=MTR-031`
selects the registry/sample directly. Existing evidence-intake review proposals,
file filtering, automatic workflow navigation and expandable tray remain available.
