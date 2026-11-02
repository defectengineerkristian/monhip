using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Text;

namespace MonhipInstaller
{
	public static class Http
	{
		private static HttpWebRequest Request(string url, int timeout)
		{
			HttpWebRequest httpWebRequest = (HttpWebRequest)WebRequest.Create(url);
			httpWebRequest.UserAgent = "Monhip-Installer";
			httpWebRequest.Timeout = timeout;
			httpWebRequest.ReadWriteTimeout = Math.Max(timeout, 60000);
			return httpWebRequest;
		}

		public static string GetString(string url, int timeout, bool github)
		{
			HttpWebRequest httpWebRequest = Request(url, timeout);
			httpWebRequest.AutomaticDecompression = DecompressionMethods.GZip | DecompressionMethods.Deflate;
			if (github)
			{
				httpWebRequest.Accept = "application/vnd.github+json";
			}
			using (WebResponse webResponse = httpWebRequest.GetResponse())
			{
				using (StreamReader streamReader = new StreamReader(webResponse.GetResponseStream(), Encoding.UTF8))
				{
					return streamReader.ReadToEnd();
				}
			}
		}

		public static object GetJson(string url, int timeout)
		{
			return Json.Parse(GetString(url, timeout, true));
		}

		public static int Status(WebException e)
		{
			HttpWebResponse httpWebResponse = e.Response as HttpWebResponse;
			if (httpWebResponse != null)
			{
				return (int)httpWebResponse.StatusCode;
			}
			return 0;
		}

		public static long HeadSize(string url)
		{
			HttpWebRequest httpWebRequest = Request(url, 30000);
			httpWebRequest.Method = "HEAD";
			using (HttpWebResponse httpWebResponse = (HttpWebResponse)httpWebRequest.GetResponse())
			{
				string text = httpWebResponse.Headers["x-linked-size"];
				long result;
				return (text != null && long.TryParse(text, out result)) ? result : Math.Max(0L, httpWebResponse.ContentLength);
			}
		}

		public static long Download(string url, string dest, long done, long total, bool resume, ProgressFn progress, Cancel cancel)
		{
			string text = LocalPath(url);
			if (text != null)
			{
				File.Copy(text, dest, true);
				long length = new FileInfo(dest).Length;
				progress(done + length, (total > 0) ? total : (done + length));
				return done + length;
			}
			long num = ((resume && File.Exists(dest)) ? new FileInfo(dest).Length : 0);
			HttpWebRequest httpWebRequest = Request(url, 30000);
			if (num > 0)
			{
				httpWebRequest.AddRange(num);
			}
			HttpWebResponse httpWebResponse;
			try
			{
				httpWebResponse = (HttpWebResponse)httpWebRequest.GetResponse();
			}
			catch (WebException e)
			{
				if (num > 0 && Status(e) == 416)
				{
					progress(done + num, total);
					return done + num;
				}
				throw;
			}
			using (httpWebResponse)
			{
				bool flag = httpWebResponse.StatusCode == HttpStatusCode.PartialContent;
				if (!flag)
				{
					num = 0L;
				}
				done += num;
				if (total <= 0)
				{
					total = num + Math.Max(0L, httpWebResponse.ContentLength);
				}
				Stopwatch stopwatch = Stopwatch.StartNew();
				using (Stream stream = httpWebResponse.GetResponseStream())
				{
					using (FileStream fileStream = new FileStream(dest, flag ? FileMode.Append : FileMode.Create, FileAccess.Write))
					{
						byte[] array = new byte[1048576];
						int num2;
						while ((num2 = stream.Read(array, 0, array.Length)) > 0)
						{
							cancel.Check();
							fileStream.Write(array, 0, num2);
							done += num2;
							if (stopwatch.ElapsedMilliseconds >= 200)
							{
								progress(done, total);
								stopwatch.Restart();
							}
						}
					}
				}
			}
			progress(done, total);
			return done;
		}

		private static string LocalPath(string url)
		{
			if (url.StartsWith("file:", StringComparison.OrdinalIgnoreCase))
			{
				return new Uri(url).LocalPath;
			}
			if (!File.Exists(url))
			{
				return null;
			}
			return url;
		}
	}
}
