using System.Drawing;

namespace ShaYu;

/// <summary>内嵌的多尺寸应用图标（16/24/32/48/64/128/256），取不到就退回系统图标。</summary>
internal static class AppIcon
{
    private static Icon? _cached;

    public static Icon Get
    {
        get
        {
            if (_cached is not null) return _cached;
            try
            {
                using var s = typeof(AppIcon).Assembly.GetManifestResourceStream("ShaYu.icon.ico");
                if (s is not null) _cached = new Icon(s);
            }
            catch { }
            return _cached ??= SystemIcons.Application;
        }
    }
}
