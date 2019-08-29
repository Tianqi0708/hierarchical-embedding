import os
os.environ["PYTHON_EGG_CACHE"] = "/rds/projects/2018/hesz01/poincare-embeddings/python-eggs"


import numpy as np
import networkx as nx
import pandas as pd

import argparse

from hie.utils import load_embedding, load_data

from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.metrics.pairwise import euclidean_distances

import functools
import fcntl

def minkowki_dot(u, v):
	"""
	`u` and `v` are vectors in Minkowski space.
	"""
	rank = u.shape[-1] - 1
	euc_dp = u[:,:rank].dot(v[:,:rank].T)
	return euc_dp - u[:,rank, None] * v[:,rank]

def hyperbolic_distance_hyperboloid(u, v):
	mink_dp = minkowki_dot(u, v)
	mink_dp = np.maximum(-1 - mink_dp, 1e-15)
	return np.arccosh(1 + mink_dp)

def hyperbolic_distance_poincare(X):
	norm_X = np.linalg.norm(X, keepdims=True, axis=-1)
	norm_X = np.minimum(norm_X, np.nextafter(1,0, ))
	uu = euclidean_distances(X) ** 2
	dd = (1 - norm_X**2) * (1 - norm_X**2).T
	return np.arccosh(1 + 2 * uu / dd)

def evaluate_rank_and_MAP(args, dists, edgelist):
	assert not isinstance(edgelist, dict)

	if not isinstance(edgelist, np.ndarray):
		edgelist = np.array(edgelist)

	#if not isinstance(non_edgelist, np.ndarray):
	#	non_edgelist = np.array(non_edgelist)

	ranksum=0
	nranks=0
	adj={}
	for x, y in edgelist:
		if x in adj:
			adj[x].add(y)
		else:
			adj[x]={y}
		if not args.directed:
			if y in adj:
				adj[y].add(x)
			else:
				adj[y]={x}
	print('loaded adjcency')
	labels=np.empty(len(dists[0]))
	ap_score=0
	auc_score=0
	iters=0
	for v in adj:
		labels.fill(0)
		neighbors=np.array(list(adj[v]))
		dist=dists[v]
		dist[v]=1e12
		a=sorted([(e, i) for i,e in enumerate(dist)], key=lambda x:x[0])
		#print('sorted pairs')
		sorted_dists, sorted_idx=[x for x, _ in a], [x for _, x in a]
		ranks, =np.where(np.in1d(sorted_idx, neighbors))
		ranks+=1
		N=ranks.shape[0]
		iters+=1
		ranksum+=ranks.sum()-(N*(N-1)/2)
		nranks+=ranks.shape[0]
		labels[neighbors]=1
		#labels=labels[sorted_idx]
		#dist=dist[sorted_idx]
		#print('computing scores')
		# ap_score+=average_precision_score(labels, -dist)
		# auc_score+=roc_auc_score(labels, -dist)
		ap_score+=average_precision_score(labels, -dist)
		auc_score+=roc_auc_score(labels, -dist)
	#idx=non_edge_dists.argsort()
	ranks=float(ranksum)/nranks
	ap_score=ap_score/iters
	auc_score=auc_score/iters
	print ("MEAN RANK =", ranks, "AP =", ap_score, 
		"AUROC =", auc_score)

	return ranks, ap_score, auc_score

#	edge_dists = dists[edgelist[:,0], edgelist[:,1]]
#	non_edge_dists = dists[non_edgelist[:,0], non_edgelist[:,1]]
	

#	labels = np.append(np.ones_like(edge_dists), np.zeros_like(non_edge_dists))
#	scores = -np.append(edge_dists, non_edge_dists)
#	ap_score = average_precision_score(labels, scores) # macro by default
#	auc_score = roc_auc_score(labels, scores)
	
#	idx = non_edge_dists.argsort()
#	ranks = np.searchsorted(non_edge_dists, edge_dists, sorter=idx) + 1
#	ranks = ranks.mean()

#	print ("MEAN RANK =", ranks, "AP =", ap_score, 
#		"AUROC =", auc_score)

#	return ranks, ap_score, auc_score


def touch(path):
	with open(path, 'a'):
		os.utime(path, None)

def read_edgelist(fn):
	edges = []
	with open(fn, "r") as f:
		for line in (l.rstrip() for l in f.readlines()):
			edge = tuple(int(i) for i in line.split("\t"))
			edges.append(edge)
	return edges

def lock_method(lock_filename):
	''' Use an OS lock such that a method can only be called once at a time. '''

	def decorator(func):

		@functools.wraps(func)
		def lock_and_run_method(*args, **kwargs):

			# Hold program if it is already running 
			# Snippet based on
			# http://linux.byexamples.com/archives/494/how-can-i-avoid-running-a-python-script-multiple-times-implement-file-locking/
			fp = open(lock_filename, 'r+')
			done = False
			while not done:
				try:
					fcntl.lockf(fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
					done = True
				except IOError:
					pass
			return func(*args, **kwargs)

		return lock_and_run_method

	return decorator 

def threadsafe_fn(lock_filename, fn, *args, **kwargs ):
	lock_method(lock_filename)(fn)(*args, **kwargs)

def save_test_results(filename, seed, data, ):
	d = pd.DataFrame(index=[seed], data=data)
	if os.path.exists(filename):
		test_df = pd.read_csv(filename, sep=",", index_col=0)
		test_df = d.combine_first(test_df)
	else:
		test_df = d
	test_df.to_csv(filename, sep=",")

def threadsafe_save_test_results(lock_filename, filename, seed, data):
	threadsafe_fn(lock_filename, save_test_results, filename=filename, seed=seed, data=data)


def parse_args():

	parser = argparse.ArgumentParser(description='Load Hyperboloid Embeddings and evaluate reconstruction')
	
	parser.add_argument("--edgelist", dest="edgelist", type=str, 
		help="edgelist to load.")
	parser.add_argument("--features", dest="features", type=str, 
		help="features to load.")
	parser.add_argument("--labels", dest="labels", type=str, 
		help="path to labels")

	parser.add_argument('--directed', action="store_true", help='flag to train on directed graph')

	parser.add_argument("--embedding", dest="embedding_filename",  
		help="path of embedding to load.")

	parser.add_argument("--test-results-dir", dest="test_results_dir",  
		help="path to save results.")
	
	parser.add_argument("--seed", type=int, default=0)


	parser.add_argument("--poincare", action="store_true")


	return parser.parse_args()


def main():

	args = parse_args()

	graph, features, node_labels = load_data(args)
	print ("Loaded dataset")

	embedding_df = load_embedding(args.embedding_filename)
	#embedding = embedding_df.values
	# row 0 is embedding for node 0
	# row 1 is embedding for node 1 etc...
	embedding = embedding_df.values

	if args.poincare:
		dists = hyperbolic_distance_poincare(embedding)
	else:
		dists = hyperbolic_distance_hyperboloid(embedding, embedding)
	print('computed distances')
	# test_edges = list(graph.edges())
	# test_non_edges = list(nx.non_edges(graph))

	test_results = dict()
	edges=[]
	edges=list(graph.edges())
	print('loaded edges')
	(mean_rank_recon, ap_recon, roc_recon) = evaluate_rank_and_MAP(args, dists, edges)

	test_results.update({"mean_rank_recon": mean_rank_recon, 
		"ap_recon": ap_recon,
		"roc_recon": roc_recon})

	test_results_dir = args.test_results_dir
	if not os.path.exists(test_results_dir):
		os.makedirs(test_results_dir)
	test_results_filename = os.path.join(test_results_dir, "test_results.csv")
	test_results_lock_filename = os.path.join(test_results_dir, "test_results.lock")
	touch(test_results_lock_filename)

	print ("saving test results to {}".format(test_results_filename))

	threadsafe_save_test_results(test_results_lock_filename, test_results_filename, args.seed, data=test_results )

	print ("done")
	
if __name__ == "__main__":
	main()
