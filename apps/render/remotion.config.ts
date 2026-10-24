import { Config } from "@remotion/cli/config";
import { webpackOverride } from "./src/webpackOverride";

Config.overrideWebpackConfig(webpackOverride);
