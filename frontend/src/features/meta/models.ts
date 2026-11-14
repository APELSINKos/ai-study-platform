/** The built-in analyser and embedder name their models with this prefix. */
const BUILT_IN_MODEL_PREFIX = "mock-";

/** Whether a model is one of the built-in ones, which need no API key and no AI service. */
export function isBuiltInModel(model: string | null): boolean {
  return model?.startsWith(BUILT_IN_MODEL_PREFIX) === true;
}
