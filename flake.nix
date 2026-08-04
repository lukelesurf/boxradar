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
          ];
        };
      });
}
