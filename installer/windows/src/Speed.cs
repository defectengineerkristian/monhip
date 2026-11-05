using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;

namespace MonhipInstaller
{
	public class Speed
	{
		private readonly Stopwatch sw = Stopwatch.StartNew();

		private long start = -1L;

		public string Text(string name, long done, long total)
		{
			if (start < 0)
			{
				start = done;
			}
			double totalSeconds = sw.Elapsed.TotalSeconds;
			double num = ((totalSeconds > 1.0) ? ((double)(done - start) / totalSeconds) : 0.0);
			List<string> list = new List<string>();
			list.Add("Lade " + name + " …");
			List<string> list2 = list;
			list2.Add((total > 0) ? string.Format("{0:0} % ({1} von {2})", (double)done * 100.0 / (double)total, Fmt.Size(done), Fmt.Size(total)) : Fmt.Size(done));
			if (num > 0.0)
			{
				list2.Add(string.Format(new CultureInfo("de-DE"), "{0:0.0} MB/s", num / 1048576.0));
				if (total > 0)
				{
					double num2 = (double)(total - done) / num;
					list2.Add((num2 >= 90.0) ? string.Format("noch etwa {0:0} min", num2 / 60.0) : string.Format("noch {0:0} s", num2));
				}
			}
			return string.Join("  ·  ", list2);
		}
	}
}
