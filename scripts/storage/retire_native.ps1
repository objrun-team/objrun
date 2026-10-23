# Native .NET file operations remain inside this PowerShell process. All targets
# are individually checked literal paths. Directory deletion is never recursive.
if (-not ('ObjRunRetireNative' -as [type])) {
Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.IO.Compression;
using System.Collections.Generic;
using System.Globalization;
using System.Text;
public static class ObjRunRetireNative {
    public static long Execute(string root, string manifest, string journal) {
        return Execute(root, manifest, journal, Array.Empty<string>());
    }
    public static long Execute(string root, string manifest, string journal, string[] preservePaths) {
        root = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar);
        string prefix = root + Path.DirectorySeparatorChar;
        var keep = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var p in preservePaths) {
            string path = Path.GetFullPath(p).TrimEnd(Path.DirectorySeparatorChar);
            if (path != root && !path.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("Preservation path outside source");
            keep.Add(path);
        }
        var dirs = new List<string>();
        long deleted = 0;
        using (var input = new StreamReader(new GZipStream(File.OpenRead(manifest), CompressionMode.Decompress), Encoding.UTF8))
        using (var log = new StreamWriter(journal, true, new UTF8Encoding(false))) {
            string line;
            while ((line = input.ReadLine()) != null) {
                string[] row = line.Split('\t');
                if (row.Length != 4) throw new InvalidDataException("Invalid manifest row");
                string path = Path.GetFullPath(Path.Combine(root, row[1]));
                if (!path.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("Path escaped verified root");
                var attr = File.GetAttributes(path);
                if (row[0] == "dir") {
                    if ((attr & FileAttributes.Directory) == 0 || (attr & FileAttributes.ReparsePoint) != 0) throw new IOException("Directory changed");
                    dirs.Add(path); continue;
                }
                if (row[0] == "link") {
                    if ((attr & FileAttributes.ReparsePoint) == 0) throw new IOException("Link changed");
                    if ((attr & FileAttributes.Directory) != 0) Directory.Delete(path, false); else File.Delete(path);
                    continue;
                }
                if (row[0] != "file" || (attr & (FileAttributes.ReparsePoint | FileAttributes.Directory)) != 0) throw new IOException("File type changed");
                var file = new FileInfo(path);
                long bytes = long.Parse(row[2], CultureInfo.InvariantCulture);
                long mtime = long.Parse(row[3], CultureInfo.InvariantCulture);
                if (file.Length != bytes || checked((file.LastWriteTimeUtc.Ticks - DateTime.UnixEpoch.Ticks) * 100L) != mtime) throw new IOException("File changed immediately before cleanup: " + path);
                if (keep.Contains(path)) continue;
                if ((attr & FileAttributes.ReadOnly) != 0) File.SetAttributes(path, attr & ~FileAttributes.ReadOnly);
                File.Delete(path);
                deleted++;
                if (deleted % 10000 == 0) {
                    string message = "{\"event\":\"files_removed\",\"total\":" + deleted.ToString(CultureInfo.InvariantCulture) + "}";
                    log.WriteLine(message); log.Flush(); Console.WriteLine(message);
                }
            }
            for (int i=dirs.Count-1; i>=0; i--) if (!keep.Contains(dirs[i])) DeleteEmptyDirectory(dirs[i]);
            if (!keep.Contains(root)) DeleteEmptyDirectory(root);
            log.WriteLine("{\"event\":\"native_complete\",\"total\":" + deleted.ToString(CultureInfo.InvariantCulture) + "}");
        }
        return deleted;
    }
    static void DeleteEmptyDirectory(string path) {
        var attr = File.GetAttributes(path);
        if ((attr & FileAttributes.Directory) == 0 || (attr & FileAttributes.ReparsePoint) != 0) throw new IOException("Directory type changed");
        // Go module caches mark directories read-only. This is a DOS attribute,
        // not an ACL change. Contents are already verified and removed above.
        if ((attr & FileAttributes.ReadOnly) != 0) File.SetAttributes(path, attr & ~FileAttributes.ReadOnly);
        Directory.Delete(path, false);
    }
    public static long ResumeEmptyDirectories(string root, string manifest, string journal) {
        return ResumeEmptyDirectories(root, manifest, journal, Array.Empty<string>());
    }
    public static long ResumeEmptyDirectories(string root, string manifest, string journal, string[] preserveRoots) {
        root = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar);
        string prefix = root + Path.DirectorySeparatorChar;
        var skip = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var keep = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var value in preserveRoots) {
            string path = Path.GetFullPath(value).TrimEnd(Path.DirectorySeparatorChar);
            if (!path.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("Preserved root outside source");
            skip.Add(path);
            while (path.Length >= root.Length) {
                keep.Add(path); if (path == root) break;
                path = Path.GetDirectoryName(path);
            }
        }
        var known = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        known.Add(root);
        using (var input = new StreamReader(new GZipStream(File.OpenRead(manifest), CompressionMode.Decompress), Encoding.UTF8)) {
            string line;
            while ((line = input.ReadLine()) != null) {
                string[] row = line.Split('\t');
                if (row.Length != 4) throw new InvalidDataException("Invalid manifest");
                string path = Path.GetFullPath(Path.Combine(root, row[1]));
                if (!path.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("Path escaped source");
                if (row[0] == "dir") known.Add(path);
            }
        }
        var stack = new Stack<string>(); var remaining = new List<string>(); stack.Push(root);
        while (stack.Count > 0) {
            string path = stack.Pop();
            if (skip.Contains(path)) continue;
            if (!known.Contains(path)) throw new IOException("Unexpected directory after cleanup");
            var attr = File.GetAttributes(path);
            if ((attr & FileAttributes.Directory) == 0 || (attr & FileAttributes.ReparsePoint) != 0) throw new IOException("Unexpected file or link after cleanup");
            remaining.Add(path);
            foreach (var child in Directory.EnumerateFileSystemEntries(path)) stack.Push(child);
        }
        // The complete remaining tree was checked before any resumed deletion.
        long deleted = 0;
        for (int i=remaining.Count-1; i>=0; i--) if (!keep.Contains(remaining[i])) { DeleteEmptyDirectory(remaining[i]); deleted++; }
        File.AppendAllText(journal,"{\"event\":\"empty_directory_cleanup_resumed\",\"directories\":" + deleted.ToString(CultureInfo.InvariantCulture) + "}\n");
        return deleted;
    }
}
'@
}
