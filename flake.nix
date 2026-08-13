{
  description = "BOXRADAR v2 — ADS-B radar on a Cheap Yellow Display";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
      in
      {
        devShells.default = pkgs.mkShell {
          name = "boxradar";

          packages = with pkgs; [
            # FHS-wrapped variant: PlatformIO downloads prebuilt xtensa
            # toolchains that need a normal /lib to run on NixOS
            platformio
            # airspace codegen (boxradar_site.geo) — note the Pi runs
            # shapely 1.8 from apt while this is 2.x, so geometry tests
            # compare with tolerance rather than equality.
            #
            # flask is for boxradar_config, the site configuration UI. The
            # rule it has to satisfy is "installable from apt on a Debian
            # Pi", not "installable at all" — python3-flask is in bookworm,
            # which is why it is allowed where pip is not.
            (python3.withPackages (ps: [ ps.pyyaml ps.shapely ps.flask ]))
            # tools/receiver-install is bash, and the receiver provisions a Pi
            # from a bare image — a shell bug there strands a box in someone
            # else's house, so every stage script is linted.
            shellcheck
          ];
        };
      });
}
