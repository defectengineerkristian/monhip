using System;
using System.Linq;
using System.Net;

namespace MonhipInstaller
{
	public static class GitHub
	{
		private const string Api = "https://api.github.com/repos/";

		public static Latest Get(string repo, string branch, int timeout)
		{
			object obj = null;
			try
			{
				obj = Http.GetJson("https://api.github.com/repos/" + repo + "/releases/latest", timeout);
			}
			catch (WebException e)
			{
				if (Http.Status(e) != 404)
				{
					throw;
				}
			}
			if (string.IsNullOrEmpty(branch))
			{
				branch = Json.Str(Http.GetJson("https://api.github.com/repos/" + repo, timeout), "default_branch");
			}
			string stringToEscape = ((obj != null) ? Json.Str(obj, "tag_name") : branch);
			object json = Http.GetJson("https://api.github.com/repos/" + repo + "/commits/" + Uri.EscapeDataString(stringToEscape), timeout);
			Latest latest = new Latest();
			latest.Sha = Json.Str(json, "sha");
			latest.Branch = branch;
			latest.Date = Json.Str(Json.Get(Json.Get(json, "commit"), "committer"), "date");
			if (latest.Date.Length > 10)
			{
				latest.Date = latest.Date.Substring(0, 10);
			}
			latest.Label = ((obj != null) ? Json.Str(obj, "tag_name") : latest.Sha.Substring(0, Math.Min(7, latest.Sha.Length)));
			latest.Source = ((obj != null) ? "release" : "commit");
			latest.Zip = "https://codeload.github.com/" + repo + "/zip/" + latest.Sha;
			if (obj != null)
			{
				latest.Notes = (from x in Json.Str(obj, "body").Split('\n')
					select x.Trim().TrimStart('-', '*', ' ') into x
					where x.Length > 0
					select x).Take(12).ToList();
			}
			return latest;
		}

		public static Latest CheckUpdate(InstallInfo info, int timeout)
		{
			Latest latest = Get(info.Repo, info.Branch, timeout);
			if (latest.Sha == info.Version)
			{
				return null;
			}
			if (!string.IsNullOrEmpty(info.Version))
			{
				try
				{
					object json = Http.GetJson("https://api.github.com/repos/" + info.Repo + "/compare/" + info.Version + "..." + latest.Sha, timeout);
					string text = Json.Str(json, "status");
					if (text == "behind" || text == "identical")
					{
						return null;
					}
					if (latest.Notes.Count == 0)
					{
						latest.Notes = (from x in Json.Arr(json, "commits")
							select Json.Str(Json.Get(x, "commit"), "message").Split('\n')[0].Trim()).Reverse().Take(10).Reverse()
							.ToList();
					}
				}
				catch (WebException)
				{
				}
			}
			return latest;
		}
	}
}
