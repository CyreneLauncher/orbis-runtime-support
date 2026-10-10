# orbis-runtime-support

The Orbis PRX runtime every native port links, and the build toolkit that links it.
See PORT-PROVENANCE.json for exact origins.

- `native_dlfcn.c`, `orbis_prx_tls.c`, `orbis_initializers.c`, `orbis_runtime.c`, `orbis_runtime.h`
  and `prepare_jvm_link.py`: the runtime objects and link script every JVM-loadable module carries.
- `orbis_prx.py`: compiles, links, audits and signs a PRX with those objects.
- `build_stamp.py`: skips a component build whose inputs are unchanged.
- `pinned_archive.py`: downloads an upstream archive and checks it against a pin the calling
  port supplies. Each port keeps its own pins.

This repository depends on no other port. Ports find it as a sibling checkout named
`orbis-runtime-support`, or through `ORBIS_RUNTIME_SUPPORT`.

Integration tests and package assembly remain in orbis-launcher.
