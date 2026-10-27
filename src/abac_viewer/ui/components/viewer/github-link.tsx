import { useMetaSuspense } from "@/lib/api";

/** Build a GitHub deep link to a config file from a "file:line" source string
 * (as carried on chain-detail nodes) using build info from /api/meta. Returns
 * null when we don't have a repo slug or a source. */
export function useGithubLinker(): (source?: string | null) => string | null {
  const { data } = useMetaSuspense({});
  const { repo_slug, build_sha, config_path_prefix } = data.data;
  return (source?: string | null) => {
    if (!source || !repo_slug) return null;
    const [file, line] = source.split(":");
    const path = `${config_path_prefix}/${file}`.replace(/^\/+/, "");
    const url = `https://github.com/${repo_slug}/blob/${build_sha}/${path}`;
    return line ? `${url}#L${line}` : url;
  };
}
