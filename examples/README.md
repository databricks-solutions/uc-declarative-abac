# Examples

- [**finance_demo**](./finance_demo/): a complete, deployable-from-scratch
  governance project for a fictional financial-services organisation. One logical catalog
  deployed to `prod` and `uat`, a medallion layout (bronze → silver → gold) per business
  sub-domain, a nested group hierarchy, governed tags, and mask / filter / grant policies.
  It exercises every GA feature of the engine and is a good starting point to copy into your
  own governance repo.
- [**abac_viewer_demo**](./abac_viewer_demo/): a small demo catalog with nested groups of
  demo service principals and grant, mask, and filter policies, deployed together with the
  ABAC Policy Explorer app that visualises who can see what.
