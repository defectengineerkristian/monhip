using System;

namespace MonhipInstaller
{
	public class Cancel
	{
		private volatile bool set;

		public bool IsSet
		{
			get
			{
				return set;
			}
		}

		public void Set()
		{
			set = true;
		}

		public void Check()
		{
			if (set)
			{
				throw new OperationCanceledException("abgebrochen");
			}
		}
	}
}
