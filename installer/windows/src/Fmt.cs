using System;
using System.Globalization;

namespace MonhipInstaller
{
	public static class Fmt
	{
		private static readonly CultureInfo De = new CultureInfo("de-DE");

		public static string Size(long n)
		{
			if (n < 1048576)
			{
				return "unter 1 MB";
			}
			if (n < 1073741824)
			{
				return string.Format(De, "{0:0} MB", (double)n / 1048576.0);
			}
			return Gb((double)n / 1073741824.0);
		}

		public static string Gb(double gb)
		{
			return string.Format(De, (gb >= 100.0) ? "{0:0} GB" : "{0:0.0} GB", gb);
		}

		public static string Date(string iso)
		{
			DateTime result;
			if (iso == null || iso.Length < 10 || !DateTime.TryParseExact(iso.Substring(0, 10), "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out result))
			{
				return "";
			}
			return result.ToString("dd.MM.yyyy");
		}

		public static string Quote(string s)
		{
			return "\"" + s + "\"";
		}
	}
}
