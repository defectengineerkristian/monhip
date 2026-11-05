namespace MonhipInstaller
{
	public class Options
	{
		public string Ziel;

		public string Quelle;

		public string Ordner;

		public bool OhneVerknuepfungen;

		public bool Auto;

		public bool NurProgramm;

		public bool Manage;

		public bool Uninstall;

		public static Options Parse(string[] args)
		{
			Options options = new Options();
			for (int i = 0; i < args.Length; i++)
			{
				string text = args[i].TrimStart('-', '/').ToLowerInvariant();
				string text2 = ((i + 1 < args.Length) ? args[i + 1] : null);
				if (text == "ziel" && text2 != null)
				{
					options.Ziel = text2;
					i++;
					continue;
				}
				if (text == "quelle" && text2 != null)
				{
					options.Quelle = text2;
					i++;
					continue;
				}
				if (text == "ordner" && text2 != null)
				{
					options.Ordner = text2;
					i++;
					continue;
				}
				switch (text)
				{
				case "ohne-verknuepfungen":
					options.OhneVerknuepfungen = true;
					break;
				case "auto":
					options.Auto = true;
					break;
				case "nur-programm":
					options.NurProgramm = true;
					break;
				case "verwalten":
					options.Manage = true;
					break;
				case "deinstallieren":
					options.Uninstall = true;
					break;
				}
			}
			return options;
		}
	}
}
