# test_index.py
# Copyright (C) 2008, 2009 Michael Trier (mtrier@gmail.com) and contributors
#
# This module is part of GitPython and is released under
# the BSD License: http://www.opensource.org/licenses/bsd-license.php

from test.testlib import *
from git import *
import inspect
import os
import sys
import tempfile
import glob
from stat import *

class TestTree(TestBase):
	
	def test_index_file_base(self):
		# read from file
		index = IndexFile(self.rorepo, fixture_path("index"))
		assert index.entries
		assert index.version > 0
		
		# test entry
		last_val = None
		entry = index.entries.itervalues().next()
		for attr in ("path","ctime","mtime","dev","inode","mode","uid",
								"gid","size","sha","stage"):
			val = getattr(entry, attr)
		# END for each method
		
		# test update
		entries = index.entries
		assert isinstance(index.update(), IndexFile)
		assert entries is not index.entries
		
		# test stage
		index_merge = IndexFile(self.rorepo, fixture_path("index_merge"))
		assert len(index_merge.entries) == 106
		assert len(list(e for e in index_merge.entries.itervalues() if e.stage != 0 ))
		
		# write the data - it must match the original
		tmpfile = tempfile.mktemp()
		index_merge.write(tmpfile)
		fp = open(tmpfile, 'r')
		assert fp.read() == fixture("index_merge")
		fp.close()
		os.remove(tmpfile)
	
	def _cmp_tree_index(self, tree, index):
		# fail unless both objects contain the same paths and blobs
		if isinstance(tree, str):
			tree = self.rorepo.commit(tree).tree
		
		num_blobs = 0
		for blob in tree.traverse(predicate = lambda e: e.type == "blob"):
			assert (blob.path,0) in index.entries
			num_blobs += 1
		# END for each blob in tree
		assert num_blobs == len(index.entries)
	
	def test_index_file_from_tree(self):
		common_ancestor_sha = "5117c9c8a4d3af19a9958677e45cda9269de1541"
		cur_sha = "4b43ca7ff72d5f535134241e7c797ddc9c7a3573"
		other_sha = "39f85c4358b7346fee22169da9cad93901ea9eb9"
		
		# simple index from tree 
		base_index = IndexFile.from_tree(self.rorepo, common_ancestor_sha)
		assert base_index.entries
		self._cmp_tree_index(common_ancestor_sha, base_index)
		
		# merge two trees - its like a fast-forward
		two_way_index = IndexFile.from_tree(self.rorepo, common_ancestor_sha, cur_sha)
		assert two_way_index.entries
		self._cmp_tree_index(cur_sha, two_way_index)
		
		# merge three trees - here we have a merge conflict
		three_way_index = IndexFile.from_tree(self.rorepo, common_ancestor_sha, cur_sha, other_sha)
		assert len(list(e for e in three_way_index.entries.values() if e.stage != 0))
		
		
		# ITERATE BLOBS
		merge_required = lambda t: t[0] != 0
		merge_blobs = list(three_way_index.iter_blobs(merge_required))
		assert merge_blobs
		assert merge_blobs[0][0] in (1,2,3)
		assert isinstance(merge_blobs[0][1], Blob)
		
		
		# writing a tree should fail with an unmerged index
		self.failUnlessRaises(GitCommandError, three_way_index.write_tree)
		
		# removed unmerged entries
		unmerged_blob_map = three_way_index.unmerged_blobs()
		assert unmerged_blob_map
		
		# pick the first blob at the first stage we find and use it as resolved version
		three_way_index.resolve_blobs( l[0][1] for l in unmerged_blob_map.itervalues() )
		tree = three_way_index.write_tree()
		assert isinstance(tree, Tree)
		num_blobs = 0
		for blob in tree.traverse(predicate=lambda item: item.type == "blob"):
			assert (blob.path,0) in three_way_index.entries
			num_blobs += 1
		# END for each blob
		assert num_blobs == len(three_way_index.entries)
	
	@with_rw_repo('0.1.6')
	def test_index_file_diffing(self, rw_repo):
		# default Index instance points to our index
		index = IndexFile(rw_repo)
		assert index.path is not None
		assert len(index.entries)
		
		# write the file back
		index.write()
		
		# could sha it, or check stats
		
		# test diff
		# resetting the head will leave the index in a different state, and the 
		# diff will yield a few changes
		cur_head_commit = rw_repo.head.reference.commit
		ref = rw_repo.head.reset('HEAD~6', index=True, working_tree=False)
		
		# diff against same index is 0
		diff = index.diff()
		assert len(diff) == 0
		
		# against HEAD as string, must be the same as it matches index
		diff = index.diff('HEAD')
		assert len(diff) == 0
		
		# against previous head, there must be a difference
		diff = index.diff(cur_head_commit)
		assert len(diff)
		
		# we reverse the result
		adiff = index.diff(str(cur_head_commit), R=True)
		odiff = index.diff(cur_head_commit, R=False)	# now its not reversed anymore
		assert adiff != odiff
		assert odiff == diff					# both unreversed diffs against HEAD
		
		# against working copy - its still at cur_commit
		wdiff = index.diff(None)
		assert wdiff != adiff
		assert wdiff != odiff
		
		# against something unusual
		self.failUnlessRaises(ValueError, index.diff, int)
		
		# adjust the index to match an old revision
		cur_branch = rw_repo.active_branch
		cur_commit = cur_branch.commit
		rev_head_parent = 'HEAD~1'
		assert index.reset(rev_head_parent) is index
		
		assert cur_branch == rw_repo.active_branch
		assert cur_commit == rw_repo.head.commit
		
		# there must be differences towards the working tree which is in the 'future'
		assert index.diff(None)
		
		# reset the working copy as well to current head,to pull 'back' as well
		new_data = "will be reverted"
		file_path = os.path.join(rw_repo.git.git_dir, "CHANGES")
		fp = open(file_path, "w")
		fp.write(new_data)
		fp.close()
		index.reset(rev_head_parent, working_tree=True)
		assert not index.diff(None)
		assert cur_branch == rw_repo.active_branch
		assert cur_commit == rw_repo.head.commit
		fp = open(file_path)
		try:
			assert fp.read() != new_data
		finally:
			fp.close()
			
		# test full checkout
		test_file = os.path.join(rw_repo.git.git_dir, "CHANGES")
		os.remove(test_file)
		index.checkout(None, force=True)
		assert os.path.isfile(test_file)
		
		os.remove(test_file)
		index.checkout(None, force=False)
		assert os.path.isfile(test_file)
		
		# individual file
		os.remove(test_file)
		index.checkout(test_file)
		assert os.path.exists(test_file)
		
		
		
		# currently it ignore non-existing paths
		index.checkout(paths=["doesnt/exist"])
		
	
	def _count_existing(self, repo, files):
		"""
		Returns count of files that actually exist in the repository directory.
		"""
		existing = 0
		basedir = repo.git.git_dir
		for f in files:
			existing += os.path.isfile(os.path.join(basedir, f))
		# END for each deleted file
		return existing
	# END num existing helper
	
	@with_rw_repo('0.1.6')
	def test_index_mutation(self, rw_repo):
		index = rw_repo.index
		num_entries = len(index.entries)
		cur_head = rw_repo.head
		
		# remove all of the files, provide a wild mix of paths, BaseIndexEntries, 
		# IndexEntries
		def mixed_iterator():
			count = 0
			for entry in index.entries.itervalues():
				type_id = count % 4 
				if type_id == 0:	# path
					yield entry.path
				elif type_id == 1:	# blob
					yield Blob(rw_repo, entry.sha, entry.mode, entry.path)
				elif type_id == 2:	# BaseIndexEntry
					yield BaseIndexEntry(entry[:4])
				elif type_id == 3:	# IndexEntry
					yield entry
				else:
					raise AssertionError("Invalid Type")
				count += 1
			# END for each entry 
		# END mixed iterator
		deleted_files = index.remove(mixed_iterator(), working_tree=False)
		assert deleted_files
		assert self._count_existing(rw_repo, deleted_files) == len(deleted_files)
		assert len(index.entries) == 0
		
		# reset the index to undo our changes
		index.reset()
		assert len(index.entries) == num_entries
		
		# remove with working copy
		deleted_files = index.remove(mixed_iterator(), working_tree=True)
		assert deleted_files
		assert self._count_existing(rw_repo, deleted_files) == 0
		
		# reset everything
		index.reset(working_tree=True)
		assert self._count_existing(rw_repo, deleted_files) == len(deleted_files)
		
		# invalid type
		self.failUnlessRaises(TypeError, index.remove, [1])
		
		# absolute path
		deleted_files = index.remove([os.path.join(rw_repo.git.git_dir,"lib")], r=True)
		assert len(deleted_files) > 1
		self.failUnlessRaises(ValueError, index.remove, ["/doesnt/exists"])
		
		# TEST COMMITTING
		# commit changed index
		cur_commit = cur_head.commit
		commit_message = "commit default head"
		
		new_commit = index.commit(commit_message, head=False)
		assert new_commit.message == commit_message
		assert new_commit.parents[0] == cur_commit
		assert len(new_commit.parents) == 1
		assert cur_head.commit == cur_commit
		
		# same index, no parents
		commit_message = "index without parents"
		commit_no_parents = index.commit(commit_message, parent_commits=list(), head=True)
		assert commit_no_parents.message == commit_message
		assert len(commit_no_parents.parents) == 0
		assert cur_head.commit == commit_no_parents
		
		# same index, multiple parents
		commit_message = "Index with multiple parents\n    commit with another line"
		commit_multi_parent = index.commit(commit_message,parent_commits=(commit_no_parents, new_commit))
		assert commit_multi_parent.message == commit_message
		assert len(commit_multi_parent.parents) == 2
		assert commit_multi_parent.parents[0] == commit_no_parents
		assert commit_multi_parent.parents[1] == new_commit
		assert cur_head.commit == commit_multi_parent
		
		# re-add all files in lib
		# get the lib folder back on disk, but get an index without it
		index.reset(new_commit.parents[0], working_tree=True).reset(new_commit, working_tree=False)
		lib_file_path = "lib/git/__init__.py"
		assert (lib_file_path, 0) not in index.entries
		assert os.path.isfile(os.path.join(rw_repo.git.git_dir, lib_file_path))
		
		# directory
		entries = index.add(['lib'])
		assert len(entries)>1
		
		# glob 
		entries = index.reset(new_commit).add(['lib/*.py'])
		assert len(entries) == 14
		
		# missing path
		self.failUnlessRaises(GitCommandError, index.reset(new_commit).add, ['doesnt/exist/must/raise'])
		
		# blob from older revision overrides current index revision
		old_blob = new_commit.parents[0].tree.blobs[0]
		entries = index.reset(new_commit).add([old_blob])
		assert index.entries[(old_blob.path,0)].sha == old_blob.id and len(entries) == 1 
		
		# mode 0 not allowed
		null_sha = "0"*40
		self.failUnlessRaises(ValueError, index.reset(new_commit).add, [BaseIndexEntry((0, null_sha,0,"doesntmatter"))])
		
		# add new file
		new_file_relapath = "my_new_file"
		new_file_path = self._make_file(new_file_relapath, "hello world", rw_repo)
		entries = index.reset(new_commit).add([BaseIndexEntry((010644, null_sha, 0, new_file_relapath))])
		assert len(entries) == 1 and entries[0].sha != null_sha
		
		# add symlink
		if sys.platform != "win32":
			link_file = os.path.join(rw_repo.git.git_dir, "my_real_symlink")
			os.symlink("/etc/that", link_file)
			entries = index.reset(new_commit).add([link_file])
			assert len(entries) == 1 and S_ISLNK(entries[0].mode)
			print "%o" % entries[0].mode
		# END real symlink test 
		
		# add fake symlink and assure it checks-our as symlink
		fake_symlink_relapath = "my_fake_symlink"
		fake_symlink_path = self._make_file(fake_symlink_relapath, "/etc/that", rw_repo)
		fake_entry = BaseIndexEntry((0120000, null_sha, 0, fake_symlink_relapath))
		entries = index.reset(new_commit).add([fake_entry])
		assert len(entries) == 1 and S_ISLNK(entries[0].mode)
		
		# checkout the fakelink, should be a link then
		assert not S_ISLNK(os.stat(fake_symlink_path)[ST_MODE])
		os.remove(fake_symlink_path)
		index.checkout(fake_symlink_path)
		assert S_ISLNK(os.lstat(fake_symlink_path)[ST_MODE])
		
